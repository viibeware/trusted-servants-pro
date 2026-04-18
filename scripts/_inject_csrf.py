"""One-off script to inject a Flask-WTF csrf_token hidden input into every
POST form in the templates/ tree. Idempotent: skips forms that already have it.
"""
import re
from pathlib import Path

CSRF_INPUT = '<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">'

FORM_OPEN = re.compile(
    r'(<form\b[^>]*method\s*=\s*"post"[^>]*>)',
    re.IGNORECASE | re.DOTALL,
)

templates = Path(__file__).resolve().parent.parent / "app" / "templates"
total = 0
for path in sorted(templates.rglob("*.html")):
    src = path.read_text()
    out = []
    last = 0
    changed = False
    for m in FORM_OPEN.finditer(src):
        out.append(src[last:m.end()])
        # Look ahead up to ~200 chars to see if csrf_token is already present
        tail = src[m.end():m.end() + 300]
        if "csrf_token()" not in tail:
            out.append("\n" + CSRF_INPUT)
            changed = True
        last = m.end()
    out.append(src[last:])
    if changed:
        path.write_text("".join(out))
        print(f"patched {path.relative_to(templates.parent.parent)}")
        total += 1
print(f"done: {total} files patched")
