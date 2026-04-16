"""Parse the existing SiteSetting.zoom_tech_content HTML into structured
sections+blocks JSON and save to SiteSetting.zoom_tech_blocks_json.

Usage:
  python scripts/parse_zoom_tech_to_blocks.py
"""
import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup, NavigableString
from app import create_app
from app.models import db, SiteSetting


def uid():
    return uuid.uuid4().hex[:8]


def html_to_md(el):
    """Basic HTML -> markdown for inline content."""
    if isinstance(el, NavigableString):
        return str(el)
    parts = []
    for c in el.children:
        if isinstance(c, NavigableString):
            parts.append(str(c))
            continue
        name = c.name
        inner = html_to_md(c)
        if name in ("strong", "b"):
            parts.append(f"**{inner}**")
        elif name in ("em", "i"):
            parts.append(f"*{inner}*")
        elif name == "a":
            href = c.get("href", "")
            parts.append(f"[{inner}]({href})")
        elif name == "br":
            parts.append("  \n")
        elif name == "code":
            parts.append(f"`{inner}`")
        elif name == "span":
            style = c.get("style", "")
            m = re.search(r"color\s*:\s*([^;]+)", style)
            if m and "red" in m.group(1).lower() or "#ff0000" in style.lower() or "#f00" in style.lower():
                parts.append(f"**{inner}**")
            else:
                parts.append(inner)
        else:
            parts.append(inner)
    return "".join(parts).strip()


def section(title=""):
    return {"id": uid(), "title": title, "blocks": []}


def block(t, data):
    return {"id": uid(), "type": t, "data": data}


def parse_blocks_from_element(node):
    """Convert a single top-level HTML element to one block (or None)."""
    name = node.name
    if name in ("p",):
        md = html_to_md(node)
        if not md:
            return None
        return block("paragraph", {"md": md})
    if name == "hr":
        return block("separator", {})
    if name in ("ul", "ol"):
        items = [html_to_md(li) for li in node.find_all("li", recursive=False)]
        return block("list", {"ordered": name == "ol", "items": items})
    if name in ("h3", "h4", "h5"):
        return block("heading", {"level": int(name[1]), "text": node.get_text().strip()})
    if name == "figure":
        img = node.find("img")
        vid = node.find("video")
        cap = node.find("figcaption")
        caption = cap.get_text().strip() if cap else ""
        if img:
            return block("image", {
                "src": img.get("src", ""),
                "alt": img.get("alt", ""),
                "caption": caption,
            })
        if vid:
            src = vid.get("src") or (vid.find("source").get("src") if vid.find("source") else "")
            return block("video", {"src": src, "poster": vid.get("poster", "")})
    if name == "img":
        return block("image", {"src": node.get("src", ""), "alt": node.get("alt", ""), "caption": ""})
    if name == "video":
        src = node.get("src") or (node.find("source").get("src") if node.find("source") else "")
        return block("video", {"src": src, "poster": node.get("poster", "")})
    if name == "pre":
        code = node.find("code")
        text = (code or node).get_text()
        lang = ""
        if code and code.get("class"):
            for cl in code.get("class"):
                if cl.startswith("language-"):
                    lang = cl[len("language-"):]
                    break
        return block("code", {"lang": lang, "code": text})
    if name == "blockquote":
        return block("callout", {"variant": "info", "title": "", "md": html_to_md(node)})
    return None


def main():
    app = create_app()
    with app.app_context():
        s = SiteSetting.query.first()
        if not s or not s.zoom_tech_content:
            print("No zoom_tech_content to parse.")
            return

        soup = BeautifulSoup(s.zoom_tech_content, "html.parser")
        sections = []
        cur = section("Introduction")
        for node in soup.children:
            if isinstance(node, NavigableString):
                text = str(node).strip()
                if text:
                    cur["blocks"].append(block("paragraph", {"md": text}))
                continue
            if node.name == "h2":
                if cur["title"] or cur["blocks"]:
                    sections.append(cur)
                cur = section(node.get_text().strip())
                continue
            b = parse_blocks_from_element(node)
            if b:
                cur["blocks"].append(b)
        if cur["title"] or cur["blocks"]:
            sections.append(cur)

        # Drop sections with no blocks AND no title
        sections = [sec for sec in sections if sec["title"] or sec["blocks"]]

        s.zoom_tech_blocks_json = json.dumps(sections)
        db.session.commit()
        print(f"Parsed into {len(sections)} sections, "
              f"{sum(len(sec['blocks']) for sec in sections)} total blocks.")
        for sec in sections:
            print(f"  - {sec['title']} ({len(sec['blocks'])} blocks)")


if __name__ == "__main__":
    main()
