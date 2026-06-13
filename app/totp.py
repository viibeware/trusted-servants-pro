# SPDX-License-Identifier: AGPL-3.0-or-later
"""Minimal RFC 6238 TOTP + recovery-code helpers.

Deliberately stdlib-only for the algorithm itself (``hmac``/``hashlib``)
so the second-factor verification path carries no third-party trust. The
defaults — HMAC-SHA1, 6 digits, 30-second period — are what every common
authenticator app assumes when it scans a bare ``otpauth://`` URI, so the
codes produced here interoperate with 2FAS, Google Authenticator, Aegis,
1Password, and the rest without any per-app tuning.

Only the QR-image rendering leans on a dependency (``qrcode`` + Pillow,
already vendored for media handling); the secret and verification never do.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

# 2FAS (and every other standard authenticator) defaults to these. They're
# baked into the provisioning URI as explicit params anyway, but keeping
# them here as the single source of truth means verify() and the URI can't
# silently drift apart.
DIGITS = 6
PERIOD = 30
ALGORITHM = "SHA1"


def generate_secret(num_bytes: int = 20) -> str:
    """Return a fresh base32 shared secret (uppercase, unpadded).

    20 bytes is the SHA1 block-friendly size RFC 4226 recommends and
    yields a 32-character key — comfortable to type by hand into an
    authenticator when scanning the QR isn't an option.
    """
    return base64.b32encode(secrets.token_bytes(num_bytes)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    """RFC 4226 HOTP for one counter value, returned as a zero-padded
    ``DIGITS``-length string."""
    # base32 secrets stored unpadded — pad back to a multiple of 8 before
    # decoding, and casefold so a manually-entered lowercase key still works.
    pad = "=" * ((8 - len(secret_b32) % 8) % 8)
    key = base64.b32decode(secret_b32.upper() + pad, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret_b32: str, code: str, *, window: int = 1, at: float | None = None) -> bool:
    """True when ``code`` is a valid TOTP for ``secret_b32`` right now.

    ``window`` steps of slack on either side (default ±1 ⇒ ±30 s) absorb
    clock drift between the server and the user's phone. Comparison is
    constant-time to avoid leaking how close a guess was.
    """
    if not secret_b32 or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit() or len(code) != DIGITS:
        return False
    now = int(at if at is not None else time.time())
    counter = now // PERIOD
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + drift), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account: str, issuer: str) -> str:
    """Build the ``otpauth://totp/...`` URI an authenticator app scans.

    ``issuer`` shows as the account label in the app; ``account`` (the
    username) disambiguates multiple accounts on the same portal.
    """
    issuer = (issuer or "Trusted Servants Pro").strip() or "Trusted Servants Pro"
    label = quote(f"{issuer}:{account}", safe="")
    params = (f"secret={secret_b32}&issuer={quote(issuer, safe='')}"
              f"&algorithm={ALGORITHM}&digits={DIGITS}&period={PERIOD}")
    return f"otpauth://totp/{label}?{params}"


def qr_data_uri(text: str) -> str:
    """Render ``text`` as a QR-code PNG and return it as a ``data:`` URI
    ready to drop into an ``<img src>``. Keeps the secret server-side
    rather than shipping a JS QR generator the secret would flow through."""
    import io
    import qrcode

    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ── Recovery codes ──────────────────────────────────────────────────────
# Single-use fallbacks so an admin who loses their authenticator isn't
# locked out of the only admin account. Stored only as SHA-256 hashes; the
# plaintext is shown once at generation and never recoverable afterward.

# Crockford-ish alphabet with the easy-to-misread glyphs (0/O, 1/I/L)
# dropped, so a code read off a printout doesn't get fat-fingered.
_RECOVERY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_recovery_codes(n: int = 10) -> list[str]:
    """Return ``n`` fresh plaintext recovery codes (``XXXXX-XXXXX``)."""
    codes = []
    for _ in range(n):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


def normalize_recovery_code(code: str) -> str:
    """Canonicalise user input — strip spaces/dashes, uppercase — so the
    hash lookup is forgiving of how the code was typed."""
    return (code or "").strip().upper().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()


def hash_recovery_codes(codes: list[str]) -> list[str]:
    return [hash_recovery_code(c) for c in codes]
