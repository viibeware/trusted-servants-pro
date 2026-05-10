"""One-shot recovery for /chat after a destructive layout-apply.

Rebuilds page.blocks_json to MATCH the page-showcase layout's stamped
shape, with the actual /chat content filled into the layout's blocks:

  • Section 1 (untitled, structural): 2-column hero —
      LEFT  column: the WhatsApp logos image
      RIGHT column: intro paragraph, "Join us on WhatsApp" CTA, and
                    the community-chats follow-up paragraph

  • Section 2 (untitled, structural): single-column container —
      heading "Chat Conduct Policy"
      intro paragraph
      bulleted guideline list
      closing paragraph + privacy link

Both sections are UNTITLED so they line up with what the showcase
layout stamps. Re-applying the layout in the admin would replace
these structural sections — preserve content by adding a section
title (any non-empty string) before re-applying.

Idempotent: always overwrites /chat with this canonical recovery
shape — re-run any time you want a fresh /chat.

Run from the host (the script reads ./data/tsp.db, the same file
the docker container bind-mounts at /data):

    python3 scripts/restore_chat_page.py

Convention matches the other one-off utilities in this directory
(see scripts/seed_chat_page.py, scripts/import_wp_*.py).
"""
import json
import os
import sqlite3
import sys
from datetime import datetime
from uuid import uuid4

DATA_DIR = os.path.abspath(os.environ.get(
    "TSP_DATA_DIR",
    os.path.join(os.path.dirname(__file__), "..", "data")))
DB_PATH = os.path.join(DATA_DIR, "tsp.db")
WA_IMG_SRC = "/pub/graphic_WhatsApp-Chat-Logos.png"

# Mirrors `_blank_page_block("container")["data"]` in app/routes.py so
# the restored containers are byte-identical to what the layout-apply
# route stamps. Keeping the seed in sync with the runtime defaults
# matters for the idempotency contract — applying the showcase layout
# to the restored page should be a no-op for the structural shape.
CONTAINER_DEFAULTS = {
    "display": "flex", "direction": "column",
    "justify": "flex-start", "align": "stretch", "wrap": False,
    "grid_columns": "repeat(2, 1fr)", "gap": "1rem",
    "padding": "1rem", "width_mode": "boxed", "max_width": 1160,
    "bg_color": "", "border_width": 0, "border_style": "solid",
    "border_color": "", "border_radius": 0, "shadow": "none",
    "hover_bg_color": "", "hover_border_color": "",
    "hover_shadow": "", "hover_lift": False,
    "blocks": [],
}


def uid():
    return uuid4().hex[:8]


def block(t, data):
    return {"id": uid(), "type": t, "data": data}


def container(extra, children):
    data = dict(CONTAINER_DEFAULTS)
    data.update(extra)
    data["blocks"] = children
    return {"id": uid(), "type": "container", "data": data}


def hero_section():
    """Section 1 — untitled 2-column hero, mirroring how the showcase
    layout's `split` entry stamps: outer grid container with two inner
    flex containers (left + right). Content is the original WhatsApp
    intro from scripts/seed_chat_page.py."""
    return {
        "id": uid(), "title": "",
        "blocks": [container(
            {"display": "grid", "grid_columns": "1fr 1fr",
             "gap": "2.5rem", "padding": "0", "align": "center"},
            [
                container(
                    {"padding": "0", "gap": "1rem",
                     "max_width": 0, "width_mode": "full"},
                    [block("image", {
                        "src": WA_IMG_SRC,
                        "alt": "WhatsApp group chat logos",
                        "caption": "",
                    })],
                ),
                container(
                    {"padding": "0", "gap": "1.25rem",
                     "max_width": 0, "width_mode": "full"},
                    [
                        block("paragraph", {"md": (
                            "Connect with your fellows between meetings "
                            "and stay up to date on what's happening in "
                            "the fellowship. All you need is a free "
                            "WhatsApp account — please introduce yourself "
                            "with a profile photo and your name."
                        )}),
                        block("button", {
                            "label": "Join us on WhatsApp →",
                            "url": ("https://chat.whatsapp.com/"
                                    "D1BekuNoNiO3IZALm9Clrs?mode=gi_t"),
                            "align": "left", "style": "primary",
                            "new_tab": True,
                            "bg": "", "hover_bg": "",
                            "text_color": "", "hover_text": "",
                            "border": "", "hover_border": "",
                            "shadow": "",
                        }),
                        block("paragraph", {"md": (
                            "Our WhatsApp community has multiple "
                            "topic-specific group chats. Once you've "
                            "joined, check the group's description for "
                            "join links to the other chats."
                        )}),
                    ],
                ),
            ],
        )],
    }


def policy_section():
    """Section 2 — untitled single-column container holding the conduct
    policy. Matches what the showcase layout's `container` entry stamps
    (a single-column container with heading + paragraph + list inside)
    so the structure card reads it as a 1-column 'Container' row."""
    return {
        "id": uid(), "title": "",
        "blocks": [container(
            {"padding": "1.5rem", "gap": "1rem",
             "max_width": 1160, "width_mode": "boxed"},
            [
                block("heading", {
                    "level": 2, "text": "Chat Conduct Policy",
                }),
                block("paragraph", {"md": (
                    "To keep our chats welcoming and supportive, we ask "
                    "everyone to follow these guidelines:"
                )}),
                block("list", {
                    "ordered": False,
                    "items": [
                        ("Be respectful of the recovery of others — "
                         "please limit messages with triggering or "
                         "overtly offensive language or imagery."),
                        ("No shirtless / nude selfies, pornography, or "
                         "explicit content."),
                        ("No self-promotion or product sales (fundraising "
                         "for the fellowship is fine)."),
                        ("When sharing a hyperlink, give a brief context "
                         "so others know what they're clicking."),
                        ("If you have less than 24 hours of sobriety, "
                         "please reach out one-on-one rather than the "
                         "public forum."),
                        "Harassment of any kind will not be tolerated.",
                    ],
                }),
                block("paragraph", {"md": (
                    "Violations may result in message removal, removal "
                    "from the chat, and/or being blocked from the "
                    "community. WhatsApp is end-to-end encrypted — "
                    "[learn more](https://www.whatsapp.com/privacy)."
                )}),
            ],
        )],
    }


def build_blocks_json():
    return json.dumps([hero_section(), policy_section()])


def main():
    if not os.path.isfile(DB_PATH):
        raise SystemExit(f"DB not found at {DB_PATH}")
    blocks_json = build_blocks_json()
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.execute("SELECT id FROM page WHERE slug='chat'")
        row = cur.fetchone()
        if not row:
            raise SystemExit("ERROR: /chat page not found")
        conn.execute(
            "UPDATE page SET blocks_json=?, layout_key=?, updated_at=? "
            "WHERE id=?",
            (blocks_json, "page-showcase",
             datetime.utcnow().isoformat(), row[0]),
        )
        conn.commit()
        print(f"Restored /chat (id={row[0]}, blocks_json="
              f"{len(blocks_json)} bytes)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
