#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drift detector for the admin Templates page section order.

The admin page at ``app/templates/frontend_templates.html`` lists each
content-type template in alphabetical order. The page is hand-edited
(the 5 bespoke sections each carry unique form fields, so a single
loop wouldn't fit), which means a new section can land in the wrong
spot if whoever added it didn't think to slot it alphabetically.

This script reads the template, pulls out the section headings in
document order, and exits non-zero if they aren't sorted (case
insensitive). Run from the repo root:

    python3 scripts/check_template_order.py

Add it to a pre-commit hook or CI step to catch drift before a PR
lands. Returns 0 on success, 1 on drift, 2 on parse failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "templates"
    / "frontend_templates.html"
)

# Headings that appear in the file but should NOT participate in the
# alphabetical ordering check:
#   * "Reusable templates" — the page's own intro card; pinned at top.
#   * "Choose an icon"     — the icon picker modal at the bottom.
SKIP_HEADINGS = frozenset({
    "reusable templates",
    "choose an icon",
})


def collect_section_headings(src: str) -> list[tuple[int, str]]:
    """Return ``(line_number, heading)`` pairs in document order.

    Captures two shapes:
      * ``<h2>...</h2>`` literals inside the body
      * ``tpl_section("Heading", ...)`` macro calls
    Filters out the macro DEFINITION's ``<h2>{{ title }}</h2>``
    placeholder (it's a template literal, not a real heading) plus the
    ``SKIP_HEADINGS`` allow-list above.
    """
    out: list[tuple[int, str]] = []

    h2_re = re.compile(r"<h2>([^<{][^<]*)</h2>")
    tpl_re = re.compile(r'tpl_section\(\s*\n?\s*"([^"]+)"')

    for i, line in enumerate(src.splitlines(), start=1):
        m = h2_re.search(line)
        if m:
            heading = m.group(1).strip()
            if heading and heading.lower() not in SKIP_HEADINGS:
                out.append((i, heading))
            continue

    # tpl_section calls span multiple lines — search the whole source.
    # The line number is the line containing the opening "tpl_section(".
    for m in tpl_re.finditer(src):
        line_no = src.count("\n", 0, m.start()) + 1
        heading = m.group(1).strip()
        if heading and heading.lower() not in SKIP_HEADINGS:
            out.append((line_no, heading))

    out.sort()
    return out


def check(src: str) -> tuple[bool, list[str]]:
    """Return ``(is_sorted, diagnostic_lines)``."""
    pairs = collect_section_headings(src)
    if not pairs:
        return False, [
            "No section headings detected — template structure may have changed.",
        ]

    headings = [h for _, h in pairs]
    sorted_headings = sorted(headings, key=str.lower)
    if headings == sorted_headings:
        return True, [
            f"OK: {len(headings)} section headings are in alphabetical order.",
        ]

    msg = [
        f"DRIFT: {TEMPLATE_PATH.name} sections are not in alphabetical order.",
        "",
        "Current order (document order):",
    ]
    for line_no, heading in pairs:
        msg.append(f"  line {line_no}: {heading}")
    msg.append("")
    msg.append("Expected order (alphabetical, case-insensitive):")
    for heading in sorted_headings:
        msg.append(f"  {heading}")
    msg.append("")
    msg.append(
        "Move the offending sections so the headings sort alphabetically."
    )
    return False, msg


def main() -> int:
    if not TEMPLATE_PATH.exists():
        print(f"FATAL: template not found at {TEMPLATE_PATH}", file=sys.stderr)
        return 2
    src = TEMPLATE_PATH.read_text(encoding="utf-8")
    ok, lines = check(src)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
