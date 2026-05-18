# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streaming AES-256-GCM encryption for full-portal export bundles.

The bundle is the most sensitive asset the portal produces (full SQLite
DB + every upload + the Fernet seed that decrypts stored Zoom / OTP /
Turnstile credentials), so transmitting it through a TLS-terminating
proxy like Cloudflare means the edge sees plaintext during the upload.
This module lets the operator opt into client-side-style encryption: the
server encrypts the bundle with a passphrase the operator supplies on
export, the encrypted blob is what travels over the wire to the
destination, and the destination decrypts with the same passphrase
before running the import. Cloudflare's edge — and any other on-path
observer — only ever sees ciphertext.

File format (binary, no trailing newline)::

    [magic 8 bytes 'TSPENC01']
    [salt  16 bytes]
    [nonce 12 bytes]
    [ciphertext stream — variable]
    [auth tag 16 bytes]

The auth tag covers the entire ciphertext + the salt + nonce + magic
implicitly through GCM, so tampering with any byte fails verification at
finalize time. PBKDF2-HMAC-SHA256 with 600_000 iterations derives a
32-byte AES key from the passphrase + a fresh random salt per export, so
two encryptions of the same bundle with the same passphrase still
produce different ciphertext (different salt → different key).

Streaming: source and destination are both files on disk. We never
materialise the whole bundle in memory — both encrypt and decrypt walk
the input in 1 MiB blocks via ``cryptography``'s low-level Cipher
update / finalize API, so a multi-GB bundle costs O(1) memory.
"""
from __future__ import annotations

import os
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


MAGIC = b"TSPENC01"
EXT = ".enc"
_SALT_LEN = 16
_NONCE_LEN = 12
_TAG_LEN = 16
_PBKDF2_ITERS = 600_000
_BLOCK = 1024 * 1024  # 1 MiB per encrypt / decrypt cycle


class BundleDecryptError(Exception):
    """Raised when decryption fails — either wrong passphrase, a
    truncated / corrupted blob, or the magic bytes don't match. Caller
    surfaces this as a user-friendly flash."""


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_file(src_path: str, dst_path: str, passphrase: str) -> None:
    """Stream-encrypt ``src_path`` to ``dst_path`` under ``passphrase``.

    ``dst_path`` is overwritten if it exists. Caller owns both paths and
    is responsible for cleanup. Empty passphrases are rejected — there
    is no plaintext fallback at this level; the route layer decides
    whether to call this at all.
    """
    if not passphrase:
        raise ValueError("passphrase must be non-empty")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(passphrase, salt)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        dst.write(MAGIC)
        dst.write(salt)
        dst.write(nonce)
        while True:
            block = src.read(_BLOCK)
            if not block:
                break
            dst.write(enc.update(block))
        dst.write(enc.finalize())
        dst.write(enc.tag)


def is_encrypted(path: str) -> bool:
    """True iff ``path`` begins with the tsp-encrypted-bundle magic.
    Cheap header check; doesn't validate the auth tag."""
    try:
        with open(path, "rb") as f:
            head = f.read(len(MAGIC))
    except OSError:
        return False
    return head == MAGIC


def decrypt_file(src_path: str, dst_path: str, passphrase: str) -> None:
    """Stream-decrypt ``src_path`` to ``dst_path`` under ``passphrase``.

    Raises ``BundleDecryptError`` on any failure (wrong passphrase,
    magic mismatch, truncation, tampering). On any error the partial
    ``dst_path`` may exist but won't validate as a zip — caller should
    treat its presence as garbage and unlink before flashing the error.
    """
    if not passphrase:
        raise BundleDecryptError("passphrase required")
    try:
        with open(src_path, "rb") as src:
            magic = src.read(len(MAGIC))
            if magic != MAGIC:
                raise BundleDecryptError("not a tsp-encrypted bundle")
            salt = src.read(_SALT_LEN)
            nonce = src.read(_NONCE_LEN)
            if len(salt) != _SALT_LEN or len(nonce) != _NONCE_LEN:
                raise BundleDecryptError("encrypted bundle header truncated")

            # Auth tag is the last 16 bytes. Stream-decrypt everything
            # between the header and the tag.
            src.seek(0, os.SEEK_END)
            end = src.tell()
            header_len = len(MAGIC) + _SALT_LEN + _NONCE_LEN
            tag_start = end - _TAG_LEN
            body_len = tag_start - header_len
            if body_len < 0:
                raise BundleDecryptError("encrypted bundle too short")
            src.seek(tag_start)
            tag = src.read(_TAG_LEN)

            key = _derive_key(passphrase, salt)
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
                # finalize() raises InvalidTag if the passphrase was
                # wrong or any byte was modified in transit.
                dst.write(dec.finalize())
    except InvalidTag as exc:
        raise BundleDecryptError(
            "decryption failed — wrong passphrase or corrupted bundle") from exc
    except OSError as exc:
        raise BundleDecryptError(f"could not read encrypted bundle: {exc}") from exc
