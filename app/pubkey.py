# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-site public-key encryption for off-site backups (``TSPEPK01``).

This is the client half of TS Pro Backup's end-to-end encryption. The
off-site backup server issues each connected site an X25519 keypair and
hands us its **public** key (via ``/api/v1/ping``); we encrypt every
backup archive to that key before it leaves this portal, so the backup
server only ever stores ciphertext it has no key for. At restore time the
operator supplies the matching **private** key — the only thing that can
decrypt — which the backup server never holds.

This module must stay byte-for-byte compatible with the backup server's
``app/pubkey.py`` (in the ``tspro-backup`` repo): we encrypt here, the
operator decrypts there (or here, on restore). Change the envelope and you
must change it in both places. It is a sibling of ``app/bundle_crypto.py``
(the older passphrase-based ``TSPENC01`` form, still used for the manual
encrypted-export feature).

Envelope (binary, no trailing newline)::

    [magic 8 bytes  'TSPEPK01']
    [ephemeral X25519 public key 32 bytes]
    [nonce 12 bytes]
    [ciphertext stream — variable, 1 MiB blocks]
    [GCM auth tag 16 bytes]

Hybrid (ECIES-style) scheme. To encrypt to recipient public key ``R``:
generate an ephemeral keypair ``(e, E)``, compute the X25519 shared secret
``s = X25519(e, R)``, derive a 32-byte AES key
``K = HKDF-SHA256(s, salt=E‖R, info='tspro-backup-e2ee-v1')``, then
stream-encrypt under AES-256-GCM. The holder of ``r`` recomputes
``s = X25519(r, E)`` and the same ``K`` to decrypt. The GCM tag covers the
whole ciphertext; any tampering fails at finalize.

Both encrypt and decrypt walk the input in 1 MiB blocks, so a multi-GB
archive costs O(1) memory — matching ``bundle_crypto``.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey)
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption)


MAGIC = b"TSPEPK01"
EXT = ".enc"
_EPK_LEN = 32          # X25519 public key
_NONCE_LEN = 12
_TAG_LEN = 16
_KEY_LEN = 32          # AES-256
_BLOCK = 1024 * 1024   # 1 MiB per encrypt / decrypt cycle
_HKDF_INFO = b"tspro-backup-e2ee-v1"

PUB_PREFIX = "tsppk_"
PRIV_PREFIX = "tspsk_"


class E2EEKeyError(Exception):
    """Raised when a ``tsppk_`` / ``tspsk_`` key string is malformed."""


class E2EEDecryptError(Exception):
    """Raised when decryption fails — wrong private key, a truncated /
    corrupted blob, or bad magic bytes. The restore route surfaces this as
    a user-friendly flash."""


# ── key encoding ────────────────────────────────────────────────────────
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def generate_keypair() -> tuple[str, str]:
    """Return ``(public_key, private_key)`` as ``tsppk_…`` / ``tspsk_…``
    strings. Used in tests; in production the backup server mints the pair."""
    priv = X25519PrivateKey.generate()
    priv_raw = priv.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return PUB_PREFIX + _b64e(pub_raw), PRIV_PREFIX + _b64e(priv_raw)


def _load_public(public_key: str) -> X25519PublicKey:
    if not public_key or not public_key.startswith(PUB_PREFIX):
        raise E2EEKeyError("not a tsppk_ public key")
    try:
        raw = _b64d(public_key[len(PUB_PREFIX):])
        if len(raw) != _EPK_LEN:
            raise E2EEKeyError("public key wrong length")
        return X25519PublicKey.from_public_bytes(raw)
    except E2EEKeyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise E2EEKeyError(f"invalid public key: {exc}") from exc


def _load_private(private_key: str) -> X25519PrivateKey:
    if not private_key or not private_key.startswith(PRIV_PREFIX):
        raise E2EEKeyError("not a tspsk_ private key")
    try:
        raw = _b64d(private_key[len(PRIV_PREFIX):])
        if len(raw) != _KEY_LEN:
            raise E2EEKeyError("private key wrong length")
        return X25519PrivateKey.from_private_bytes(raw)
    except E2EEKeyError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise E2EEKeyError(f"invalid private key: {exc}") from exc


def fingerprint(public_key: str) -> str:
    """Short, stable, human-comparable id for a public key (first 16 hex of
    its SHA-256). Shown in the backup-target wizard so the admin can
    confirm it matches the fingerprint in the backup server's console."""
    try:
        raw = _b64d(public_key[len(PUB_PREFIX):]) if public_key.startswith(PUB_PREFIX) else b""
    except Exception:  # noqa: BLE001
        raw = b""
    if not raw:
        return "—"
    digest = hashlib.sha256(raw).hexdigest()[:16]
    return ":".join(digest[i:i + 4] for i in range(0, 16, 4))


def public_from_private(private_key: str) -> str:
    """Derive the ``tsppk_…`` public key from a ``tspsk_…`` private key.

    Used by the remote-restore endpoint to confirm a supplied private key
    matches the public key already on file for the target *before* applying
    a destructive restore — so a stolen restore token alone can't push an
    archive encrypted under an attacker's own key. Raises ``E2EEKeyError``
    on a malformed private key."""
    priv = _load_private(private_key)
    pub_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return PUB_PREFIX + _b64e(pub_raw)


def head_is_e2ee(blob: bytes) -> bool:
    """True iff ``blob`` begins with the public-key envelope magic."""
    return blob[:len(MAGIC)] == MAGIC


def is_encrypted(path: str) -> bool:
    """True iff the file at ``path`` is a ``TSPEPK01`` blob."""
    try:
        with open(path, "rb") as f:
            return head_is_e2ee(f.read(len(MAGIC)))
    except OSError:
        return False


# ── derive the symmetric key from a shared secret ──────────────────────
def _derive_key(shared: bytes, eph_pub: bytes, recip_pub: bytes) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LEN,
        salt=eph_pub + recip_pub,
        info=_HKDF_INFO,
    )
    return hkdf.derive(shared)


# ── encrypt / decrypt ───────────────────────────────────────────────────
def encrypt_to_pubkey(src_path: str, dst_path: str, public_key: str) -> None:
    """Stream-encrypt ``src_path`` to ``dst_path`` for the holder of the
    private key matching ``public_key`` (a ``tsppk_…`` string)."""
    recipient = _load_public(public_key)
    recip_raw = recipient.public_bytes(Encoding.Raw, PublicFormat.Raw)

    ephemeral = X25519PrivateKey.generate()
    eph_raw = ephemeral.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    shared = ephemeral.exchange(recipient)
    key = _derive_key(shared, eph_raw, recip_raw)

    nonce = os.urandom(_NONCE_LEN)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        dst.write(MAGIC)
        dst.write(eph_raw)
        dst.write(nonce)
        while True:
            block = src.read(_BLOCK)
            if not block:
                break
            dst.write(enc.update(block))
        dst.write(enc.finalize())
        dst.write(enc.tag)


def decrypt_with_privkey(src_path: str, dst_path: str, private_key: str) -> None:
    """Stream-decrypt ``src_path`` (a ``TSPEPK01`` blob) to ``dst_path``
    using ``private_key`` (a ``tspsk_…`` string).

    Raises ``E2EEDecryptError`` on any failure (wrong key, magic mismatch,
    truncation, tampering)."""
    priv = _load_private(private_key)
    recip_raw = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    try:
        with open(src_path, "rb") as src:
            magic = src.read(len(MAGIC))
            if magic != MAGIC:
                raise E2EEDecryptError("not a TSPEPK01 blob")
            eph_raw = src.read(_EPK_LEN)
            nonce = src.read(_NONCE_LEN)
            if len(eph_raw) != _EPK_LEN or len(nonce) != _NONCE_LEN:
                raise E2EEDecryptError("encrypted header truncated")

            src.seek(0, os.SEEK_END)
            end = src.tell()
            header_len = len(MAGIC) + _EPK_LEN + _NONCE_LEN
            tag_start = end - _TAG_LEN
            body_len = tag_start - header_len
            if body_len < 0:
                raise E2EEDecryptError("encrypted blob too short")
            src.seek(tag_start)
            tag = src.read(_TAG_LEN)

            shared = priv.exchange(X25519PublicKey.from_public_bytes(eph_raw))
            key = _derive_key(shared, eph_raw, recip_raw)
            cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
            dec = cipher.decryptor()

            src.seek(header_len)
            remaining = body_len
            with open(dst_path, "wb") as dst:
                while remaining > 0:
                    block = src.read(min(_BLOCK, remaining))
                    if not block:
                        break
                    dst.write(dec.update(block))
                    remaining -= len(block)
                dst.write(dec.finalize())
    except InvalidTag as exc:
        raise E2EEDecryptError(
            "decryption failed — wrong private key or corrupted blob") from exc
    except OSError as exc:
        raise E2EEDecryptError(f"could not read encrypted blob: {exc}") from exc
