# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
from pathlib import Path

__version__ = "1.7.13"


def _compute_build_id() -> str:
    """Content hash of the app/ source tree, computed once at import time.

    Lets the client-side update-banner detect redeploys that ship new code
    under the same __version__ string. Restarting the same container (same
    code) yields the same hash, so innocuous restarts don't flap the banner.
    """
    root = Path(__file__).resolve().parent
    h = hashlib.blake2b(digest_size=8)
    exts = {".py", ".html", ".css", ".js"}
    paths = sorted(
        p for p in root.rglob("*")
        if p.is_file()
        and p.suffix in exts
        and "__pycache__" not in p.parts
    )
    for p in paths:
        rel = p.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            continue
        h.update(b"\n")
    return h.hexdigest()


__build_id__ = _compute_build_id()
