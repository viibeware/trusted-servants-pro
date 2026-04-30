# SPDX-License-Identifier: AGPL-3.0-or-later
"""Soft-delete (recycle bin) helpers backing the Delete Log feature.

Three entry points exist for the supported source types:
``soft_delete_library_item``, ``soft_delete_meeting_file``,
``soft_delete_media``. Each captures a snapshot of the row's full
state into a ``DeletedFile`` row, leaves the on-disk file alone, and
removes the live record. ``restore`` rebuilds the original row at
its captured position; ``purge`` permanently drops the snapshot and
deletes the on-disk file iff no other live records reference it.

A 30-day default retention is applied at delete time. The exposed
``RETENTION_DAYS`` constant lets the Delete Log UI label the
auto-purge window.
"""
import os
import json
from datetime import datetime, timedelta
from flask import current_app
from .models import (db, DeletedFile, LibraryItem, MeetingFile, MediaItem,
                     LibraryCategory, Library, Meeting)


RETENTION_DAYS = 30


def _now():
    return datetime.utcnow()


def _expiry():
    return _now() + timedelta(days=RETENTION_DAYS)


# ---- Snapshot creation ------------------------------------------------------

def soft_delete_library_item(reading, deleted_by_id):
    """Snapshot a LibraryItem row + its category bindings, then delete the
    live record. The on-disk file (and thumbnail) are left alone — the
    snapshot's ``stored_filename`` keeps the connection. Returns the
    new DeletedFile id."""
    library = reading.library
    snapshot = {
        "library_id": reading.library_id,
        "title": reading.title,
        "body": reading.body,
        "url": reading.url,
        "stored_filename": reading.stored_filename,
        "original_filename": reading.original_filename,
        "thumbnail_filename": reading.thumbnail_filename,
        "position": reading.position,
        "created_by": reading.created_by,
        "created_at": reading.created_at.isoformat() if reading.created_at else None,
        # Category bindings: capture by id (fast restore when library +
        # categories are intact) AND by name (fallback when an admin
        # later renames or drops a category).
        "category_ids":   [c.id for c in reading.categories],
        "category_names": [c.name for c in reading.categories],
    }
    row = DeletedFile(
        source_type="reading",
        source_id=reading.id,
        stored_filename=reading.stored_filename,
        original_filename=reading.original_filename,
        title=reading.title,
        thumbnail_filename=reading.thumbnail_filename,
        parent_type="library" if reading.library_id else None,
        parent_id=reading.library_id,
        parent_label=(library.name if library else None),
        snapshot_json=json.dumps(snapshot),
        deleted_at=_now(),
        deleted_by=deleted_by_id,
        expires_at=_expiry(),
    )
    db.session.add(row)
    # Cascade through reading_categories — that join row is fine to
    # drop since the snapshot has the category ids/names captured.
    db.session.delete(reading)
    db.session.commit()
    return row.id


def soft_delete_meeting_file(mf, deleted_by_id):
    """Same shape as ``soft_delete_library_item`` for meeting attachments."""
    meeting = mf.meeting
    snapshot = {
        "meeting_id": mf.meeting_id,
        "category": mf.category,
        "title": mf.title,
        "description": mf.description,
        "url": mf.url,
        "stored_filename": mf.stored_filename,
        "original_filename": mf.original_filename,
        "body": mf.body,
        "position": mf.position,
        "public_visible": mf.public_visible,
        "created_at": mf.created_at.isoformat() if mf.created_at else None,
    }
    row = DeletedFile(
        source_type="meeting_file",
        source_id=mf.id,
        stored_filename=mf.stored_filename,
        original_filename=mf.original_filename,
        title=mf.title,
        parent_type="meeting" if mf.meeting_id else None,
        parent_id=mf.meeting_id,
        parent_label=(meeting.name if meeting else None),
        snapshot_json=json.dumps(snapshot),
        deleted_at=_now(),
        deleted_by=deleted_by_id,
        expires_at=_expiry(),
    )
    db.session.add(row)
    db.session.delete(mf)
    db.session.commit()
    return row.id


def soft_delete_media(media, deleted_by_id):
    """Soft-delete a File-Browser-only MediaItem. The route gating this
    already blocks deletion when other rows reference the same
    ``stored_filename``, so we don't have to chase relationships
    here — capture the row's metadata + drop the live record."""
    snapshot = {
        "stored_filename": media.stored_filename,
        "original_filename": media.original_filename,
        "content_hash": media.content_hash,
        "size_bytes": media.size_bytes,
        "mime_type": media.mime_type,
        "uploaded_by": media.uploaded_by,
        "created_at": media.created_at.isoformat() if media.created_at else None,
    }
    row = DeletedFile(
        source_type="media_item",
        source_id=media.id,
        stored_filename=media.stored_filename,
        original_filename=media.original_filename,
        title=media.original_filename,
        parent_type=None,
        parent_id=None,
        parent_label=None,
        snapshot_json=json.dumps(snapshot),
        deleted_at=_now(),
        deleted_by=deleted_by_id,
        expires_at=_expiry(),
    )
    db.session.add(row)
    db.session.delete(media)
    db.session.commit()
    return row.id


# ---- Restore ---------------------------------------------------------------

def restore(deleted_id):
    """Rebuild the original row from a snapshot. Returns ``(ok, msg)``.
    On success the DeletedFile row is dropped — restoration moves the
    item back to the live table. Failures (parent gone, unknown source
    type) leave the DeletedFile row in place so the admin can retry
    after fixing the underlying cause."""
    row = db.session.get(DeletedFile, deleted_id)
    if row is None:
        return False, "Entry not found"
    snap = json.loads(row.snapshot_json or "{}")
    if row.source_type == "reading":
        library = db.session.get(Library, snap.get("library_id"))
        if library is None:
            return False, "Library no longer exists — cannot restore."
        r = LibraryItem(
            library_id=library.id,
            title=snap.get("title") or row.title or "(restored)",
            body=snap.get("body"),
            url=snap.get("url"),
            stored_filename=snap.get("stored_filename"),
            original_filename=snap.get("original_filename"),
            thumbnail_filename=snap.get("thumbnail_filename"),
            position=snap.get("position") or 0,
            created_by=snap.get("created_by"),
        )
        db.session.add(r)
        db.session.flush()  # need r.id for the category back-fill
        # Re-attach categories: prefer the original ids when they
        # still resolve to a category in the same library; fall
        # back to lookup-by-name so renamed-or-recreated category
        # rows still get re-bound. Categories that no longer exist
        # under any name are dropped silently.
        original_ids = snap.get("category_ids") or []
        if original_ids:
            cats = (LibraryCategory.query
                    .filter(LibraryCategory.id.in_(original_ids),
                            LibraryCategory.library_id == library.id)
                    .all())
            r.categories = cats
        else:
            names = snap.get("category_names") or []
            if names:
                cats = (LibraryCategory.query
                        .filter(LibraryCategory.library_id == library.id,
                                LibraryCategory.name.in_(names))
                        .all())
                r.categories = cats
        db.session.delete(row)
        db.session.commit()
        return True, f"Restored to library “{library.name}”"

    if row.source_type == "meeting_file":
        meeting = db.session.get(Meeting, snap.get("meeting_id"))
        if meeting is None:
            return False, "Meeting no longer exists — cannot restore."
        mf = MeetingFile(
            meeting_id=meeting.id,
            category=snap.get("category") or "documents",
            title=snap.get("title") or row.title or "(restored)",
            description=snap.get("description"),
            url=snap.get("url"),
            stored_filename=snap.get("stored_filename"),
            original_filename=snap.get("original_filename"),
            body=snap.get("body"),
            position=snap.get("position") or 0,
            public_visible=bool(snap.get("public_visible")),
        )
        db.session.add(mf)
        db.session.delete(row)
        db.session.commit()
        return True, f"Restored to meeting “{meeting.name}”"

    if row.source_type == "media_item":
        # Re-add the MediaItem row. The on-disk file is still where
        # we left it because soft-delete doesn't remove disk bytes.
        m = MediaItem(
            stored_filename=snap.get("stored_filename"),
            original_filename=snap.get("original_filename") or row.original_filename or "(restored)",
            content_hash=snap.get("content_hash"),
            size_bytes=snap.get("size_bytes") or 0,
            mime_type=snap.get("mime_type"),
            uploaded_by=snap.get("uploaded_by"),
        )
        db.session.add(m)
        db.session.delete(row)
        db.session.commit()
        return True, "Restored to file browser"

    return False, f"Unknown source type: {row.source_type}"


# ---- Purge -----------------------------------------------------------------

def _live_references(stored):
    """Count live (non-trashed) rows that still reference a stored
    filename. Used by purge to decide whether the on-disk file is
    safe to delete or must be retained because something else needs
    it."""
    if not stored:
        return 0
    from .models import Meeting, Post, SiteSetting
    n = (MeetingFile.query.filter_by(stored_filename=stored).count()
         + LibraryItem.query.filter_by(stored_filename=stored).count()
         + LibraryItem.query.filter_by(thumbnail_filename=stored).count()
         + Meeting.query.filter_by(logo_filename=stored).count()
         + Post.query.filter_by(featured_image_filename=stored).count()
         + MediaItem.query.filter_by(stored_filename=stored).count())
    s = SiteSetting.query.first()
    if s and stored in (s.footer_logo_filename, s.frontend_logo_filename,
                        s.og_image_filename, s.frontend_og_image_filename,
                        s.frontend_favicon_filename,
                        s.frontend_404_image_filename):
        n += 1
    # Also: another DeletedFile may still want this file (the same
    # stored_filename can appear across multiple snapshots for dedup'd
    # uploads). Count siblings so we don't yank the bytes out from
    # under a separate trashed entry.
    return n


def _siblings_in_trash(stored, exclude_id=None):
    if not stored:
        return 0
    q = DeletedFile.query.filter(DeletedFile.stored_filename == stored)
    if exclude_id is not None:
        q = q.filter(DeletedFile.id != exclude_id)
    return q.count()


def _delete_disk_file(stored):
    if not stored:
        return
    folder = current_app.config.get("UPLOAD_FOLDER")
    if not folder:
        return
    path = os.path.join(folder, stored)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def purge(deleted_id):
    """Permanently drop a DeletedFile row. Removes the on-disk file
    only when no live reference + no other trashed snapshot still
    points at the same ``stored_filename`` — keeps deduplicated files
    intact when only one snapshot is being purged. Same logic applies
    to the thumbnail filename when present."""
    row = db.session.get(DeletedFile, deleted_id)
    if row is None:
        return False
    stored = row.stored_filename
    thumb = row.thumbnail_filename
    db.session.delete(row)
    db.session.commit()
    if stored and _live_references(stored) == 0 and _siblings_in_trash(stored) == 0:
        _delete_disk_file(stored)
    if thumb and thumb != stored and _live_references(thumb) == 0 and _siblings_in_trash(thumb) == 0:
        _delete_disk_file(thumb)
    return True


def expire_old():
    """Purge every DeletedFile whose ``expires_at`` is in the past.
    Best-effort: any row that fails to purge is logged and skipped so
    one bad row can't block the rest of the sweep."""
    cutoff = _now()
    rows = DeletedFile.query.filter(DeletedFile.expires_at < cutoff).all()
    for row in rows:
        try:
            purge(row.id)
        except Exception:
            db.session.rollback()
            try:
                current_app.logger.warning(
                    "Failed to purge expired DeletedFile id=%s", row.id)
            except Exception:
                pass
