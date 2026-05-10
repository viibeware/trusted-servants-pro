"""One-shot seeder: creates a "chat" Page row and a MediaItem for the
WhatsApp logos image. Idempotent — re-running leaves existing rows
alone.

Usage (host):  python3 scripts/seed_chat_page.py
"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from uuid import uuid4

DATA_DIR = os.path.abspath(os.environ.get("TSP_DATA_DIR",
                                          os.path.join(os.path.dirname(__file__), "..", "data")))
DB_PATH = os.path.join(DATA_DIR, "tsp.db")
UPLOAD_DIR = os.path.abspath(os.environ.get("TSP_UPLOAD_DIR",
                                            os.path.join(DATA_DIR, "uploads")))

WA_IMAGE_STORED = "4e70f0d3d49b4456934bc416f994cfd6_graphic_WhatsApp-Chat-Logos.png"
WA_IMAGE_ORIGINAL = "graphic_WhatsApp-Chat-Logos.png"


def ensure_page_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS page (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug VARCHAR(120) NOT NULL UNIQUE,
            title VARCHAR(200) NOT NULL,
            blocks_json TEXT,
            template VARCHAR(16) NOT NULL DEFAULT 'standard',
            is_published BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_page_slug ON page(slug)")


def ensure_media(conn):
    cur = conn.execute(
        "SELECT id FROM media_item WHERE stored_filename = ?",
        (WA_IMAGE_STORED,))
    if cur.fetchone():
        return
    path = os.path.join(UPLOAD_DIR, WA_IMAGE_STORED)
    if not os.path.isfile(path):
        raise SystemExit(f"Image not found at {path}")
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    conn.execute(
        "INSERT INTO media_item (stored_filename, original_filename, "
        "content_hash, size_bytes, created_at) VALUES (?, ?, ?, ?, ?)",
        (WA_IMAGE_STORED, WA_IMAGE_ORIGINAL, h.hexdigest(), size,
         datetime.utcnow().isoformat()),
    )


def build_blocks():
    """Layout-only seed. Each block carries a short neutral placeholder
    so the admin can drop in their group's own copy via the editor."""
    image_src = f"/pub/{WA_IMAGE_ORIGINAL}"

    def block(t, data):
        return {"id": uuid4().hex[:8], "type": t, "data": data}

    intro_section = {
        "id": uuid4().hex[:8],
        "title": "",
        "blocks": [
            block("image", {
                "src": image_src,
                "alt": "WhatsApp group chat logos",
                "caption": "",
            }),
            block("paragraph", {
                "md": ("Connect with your fellows between meetings and stay up "
                       "to date on what's happening in the fellowship. All "
                       "you need is a free WhatsApp account — please "
                       "introduce yourself with a profile photo and your name."),
            }),
            block("paragraph", {
                "md": ("[Join us on WhatsApp →]"
                       "(https://chat.whatsapp.com/D1BekuNoNiO3IZALm9Clrs?mode=gi_t)"),
            }),
            block("paragraph", {
                "md": ("Our WhatsApp community has multiple topic-specific "
                       "group chats. Once you've joined, check the group's "
                       "description for join links to the other chats."),
            }),
        ],
    }

    policy_section = {
        "id": uuid4().hex[:8],
        "title": "Chat Conduct Policy",
        "blocks": [
            block("paragraph", {
                "md": ("To keep our chats welcoming and supportive, we ask "
                       "everyone to follow these guidelines:"),
            }),
            block("list", {
                "ordered": False,
                "items": [
                    ("Be respectful of the recovery of others — please limit "
                     "messages with triggering or overtly offensive language "
                     "or imagery."),
                    ("No shirtless / nude selfies, pornography, or explicit "
                     "content."),
                    ("No self-promotion or product sales (fundraising for "
                     "the fellowship is fine)."),
                    ("When sharing a hyperlink, give a brief context so "
                     "others know what they're clicking."),
                    ("If you have less than 24 hours of sobriety, please "
                     "reach out one-on-one rather than the public forum."),
                    "Harassment of any kind will not be tolerated.",
                ],
            }),
            block("paragraph", {
                "md": ("Violations may result in message removal, removal "
                       "from the chat, and/or being blocked from the "
                       "community. WhatsApp is end-to-end encrypted — "
                       "[learn more](https://www.whatsapp.com/privacy)."),
            }),
        ],
    }
    return [intro_section, policy_section]


def ensure_page(conn):
    cur = conn.execute("SELECT id FROM page WHERE slug = 'chat'")
    if cur.fetchone():
        print("Page 'chat' already exists — leaving alone.")
        return
    blocks_json = json.dumps(build_blocks())
    now = datetime.utcnow().isoformat()
    conn.execute(
        "INSERT INTO page (slug, title, blocks_json, template, "
        "is_published, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("chat", "Join the chat", blocks_json, "standard", 1, now, now),
    )
    print("Inserted page row: /chat")


def main():
    if not os.path.isfile(DB_PATH):
        raise SystemExit(f"DB not found at {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    try:
        ensure_page_table(conn)
        ensure_media(conn)
        ensure_page(conn)
        conn.commit()
    finally:
        conn.close()
    print("Seed complete.")


if __name__ == "__main__":
    main()
