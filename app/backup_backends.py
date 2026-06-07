# SPDX-License-Identifier: AGPL-3.0-or-later
"""Off-site backup destinations.

Each backend implements the same minimal interface so the scheduler in
``app.backup_scheduler`` can treat FTP, SFTP, and Dropbox uniformly:

    open()                              — context-manager-ish; raises on auth failure
    put(local_path, remote_name)        — upload one file
    list() -> list[(name, size, mtime)] — list export archives at remote_path
    delete(remote_name)                 — delete one file by name
    fetch(remote_name, local_path)      — download one file
    close()

Backends never delete-then-upload; they upload first and only prune
older files after a successful put, so a transient failure can never
leave the remote without a recent backup.

Heavy imports (paramiko, dropbox) are deferred inside each class so the
app boots cleanly even if one of those wheels is missing — only the
backend the user actually picks needs its dep installed.
"""
import contextlib
import io
import logging
import os
import posixpath
import re
import socket
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from .backup import EXPORT_PREFIX

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _prefer_ipv4():
    """Force urllib3 connections opened inside this block to use IPv4.

    Docker's default bridge network is IPv4-only; getaddrinfo can still
    return AAAA records that the kernel then can't route ("Network is
    unreachable", errno 101). Patching urllib3's family selector for the
    Dropbox SDK call window avoids that without affecting other HTTP
    consumers (e.g. the WordPress importer pulling from a v6-only site)
    that may genuinely want IPv6.
    """
    try:
        from urllib3.util import connection as _uc
    except ImportError:
        yield
        return
    original = getattr(_uc, "allowed_gai_family", None)
    _uc.allowed_gai_family = lambda: socket.AF_INET
    try:
        yield
    finally:
        if original is not None:
            _uc.allowed_gai_family = original


@dataclass
class RemoteFile:
    name: str
    size: int
    mtime: float  # unix epoch; 0 if backend doesn't expose it


class BackendError(Exception):
    """Raised for any backend-layer failure (auth, network, IO).

    The wizard's "Test connection" handler and the scheduler both catch
    this and surface ``str(e)`` to the admin — keep messages user-readable.
    """


def _is_export_name(name: str) -> bool:
    """Only act on files we know we wrote.

    Guards every list/delete operation: even though ``remote_path`` is
    set by the admin, we still refuse to enumerate or prune anything
    outside our prefix so a misconfigured target pointing at /home or
    Dropbox root can't sweep the user's other files.
    """
    base = posixpath.basename(name)
    return base.startswith(EXPORT_PREFIX) and (base.endswith(".zip") or base.endswith(".zip.enc"))


# ─────────────────────────────────────────────────────────────────────
# FTP / FTPS
# ─────────────────────────────────────────────────────────────────────

class FTPBackend:
    def __init__(self, host, port, username, password, remote_path, use_tls=True):
        self.host = host
        self.port = int(port or (21 if not use_tls else 21))
        self.username = username
        self.password = password
        self.remote_path = remote_path or "/"
        self.use_tls = use_tls
        self._ftp = None

    def open(self):
        import ftplib
        try:
            if self.use_tls:
                ftp = ftplib.FTP_TLS()
                ftp.connect(self.host, self.port, timeout=30)
                ftp.login(self.username, self.password)
                ftp.prot_p()  # encrypt the data channel too
            else:
                ftp = ftplib.FTP()
                ftp.connect(self.host, self.port, timeout=30)
                ftp.login(self.username, self.password)
            self._cd(ftp, self.remote_path)
            self._ftp = ftp
        except ftplib.all_errors as e:
            raise BackendError(f"FTP connect failed: {e}") from e

    def _cd(self, ftp, path):
        """cd into path, creating directories along the way if needed."""
        import ftplib
        if not path or path == "/":
            ftp.cwd("/")
            return
        # Always start absolute so we don't accumulate relative chdirs
        # across reconnects to the same target.
        ftp.cwd("/")
        for part in [p for p in path.strip("/").split("/") if p]:
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                try:
                    ftp.mkd(part)
                    ftp.cwd(part)
                except ftplib.error_perm as e:
                    raise BackendError(f"cannot create FTP directory {part!r}: {e}") from e

    def put(self, local_path, remote_name):
        import ftplib
        try:
            with open(local_path, "rb") as f:
                self._ftp.storbinary(f"STOR {remote_name}", f)
        except ftplib.all_errors as e:
            raise BackendError(f"FTP upload failed: {e}") from e

    def list(self) -> list[RemoteFile]:
        import ftplib
        out: list[RemoteFile] = []
        try:
            # MLSD is the modern, parseable listing; fall back to NLST.
            try:
                for name, facts in self._ftp.mlsd():
                    if not _is_export_name(name):
                        continue
                    size = int(facts.get("size") or 0)
                    out.append(RemoteFile(name=name, size=size, mtime=0))
            except (ftplib.error_perm, AttributeError):
                for name in self._ftp.nlst():
                    if not _is_export_name(name):
                        continue
                    try:
                        size = self._ftp.size(name) or 0
                    except ftplib.error_perm:
                        size = 0
                    out.append(RemoteFile(name=name, size=size, mtime=0))
        except ftplib.all_errors as e:
            raise BackendError(f"FTP list failed: {e}") from e
        # No reliable mtime on every server — sort by embedded timestamp
        # in the filename (tsp-export-YYYYMMDD-HHMMSS.zip[.enc]).
        out.sort(key=lambda r: r.name, reverse=True)
        return out

    def delete(self, remote_name):
        import ftplib
        if not _is_export_name(remote_name):
            raise BackendError(f"refusing to delete non-export file {remote_name!r}")
        try:
            self._ftp.delete(remote_name)
        except ftplib.all_errors as e:
            raise BackendError(f"FTP delete failed: {e}") from e

    def fetch(self, remote_name, local_path):
        import ftplib
        try:
            with open(local_path, "wb") as f:
                self._ftp.retrbinary(f"RETR {remote_name}", f.write)
        except ftplib.all_errors as e:
            raise BackendError(f"FTP fetch failed: {e}") from e

    def close(self):
        if self._ftp is not None:
            try:
                self._ftp.quit()
            except Exception:
                try: self._ftp.close()
                except Exception: pass
            self._ftp = None


# ─────────────────────────────────────────────────────────────────────
# SFTP (SSH)
# ─────────────────────────────────────────────────────────────────────

class SFTPBackend:
    def __init__(self, host, port, username, password=None, private_key=None, remote_path="/"):
        self.host = host
        self.port = int(port or 22)
        self.username = username
        self.password = password or None
        self.private_key = private_key or None
        self.remote_path = remote_path or "/"
        self._sftp = None
        self._transport = None

    def open(self):
        try:
            import paramiko
        except ImportError as e:
            raise BackendError("SFTP backend requires the 'paramiko' package") from e
        try:
            transport = paramiko.Transport((self.host, self.port))
            pkey = None
            if self.private_key:
                pkey = self._load_private_key(self.private_key)
            transport.connect(username=self.username, password=self.password, pkey=pkey)
            sftp = paramiko.SFTPClient.from_transport(transport)
            self._mkdir_p(sftp, self.remote_path)
            sftp.chdir(self.remote_path)
            self._sftp = sftp
            self._transport = transport
        except Exception as e:
            raise BackendError(f"SFTP connect failed: {e}") from e

    def _load_private_key(self, key_text):
        """Try common key formats since paramiko has separate classes per algo."""
        import paramiko
        for cls in (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey, paramiko.DSSKey):
            try:
                return cls.from_private_key(io.StringIO(key_text))
            except paramiko.SSHException:
                continue
        raise BackendError("unrecognized private key format (tried Ed25519, ECDSA, RSA, DSA)")

    def _mkdir_p(self, sftp, path):
        if not path or path == "/":
            return
        parts = [p for p in path.strip("/").split("/") if p]
        cur = ""
        for p in parts:
            cur = cur + "/" + p
            try:
                sftp.stat(cur)
            except FileNotFoundError:
                try:
                    sftp.mkdir(cur)
                except Exception as e:
                    raise BackendError(f"cannot create remote directory {cur!r}: {e}") from e

    def put(self, local_path, remote_name):
        try:
            self._sftp.put(local_path, remote_name)
        except Exception as e:
            raise BackendError(f"SFTP upload failed: {e}") from e

    def list(self) -> list[RemoteFile]:
        try:
            out: list[RemoteFile] = []
            for attr in self._sftp.listdir_attr():
                if not _is_export_name(attr.filename):
                    continue
                out.append(RemoteFile(name=attr.filename, size=attr.st_size or 0,
                                      mtime=float(attr.st_mtime or 0)))
            out.sort(key=lambda r: r.name, reverse=True)
            return out
        except Exception as e:
            raise BackendError(f"SFTP list failed: {e}") from e

    def delete(self, remote_name):
        if not _is_export_name(remote_name):
            raise BackendError(f"refusing to delete non-export file {remote_name!r}")
        try:
            self._sftp.remove(remote_name)
        except Exception as e:
            raise BackendError(f"SFTP delete failed: {e}") from e

    def fetch(self, remote_name, local_path):
        try:
            self._sftp.get(remote_name, local_path)
        except Exception as e:
            raise BackendError(f"SFTP fetch failed: {e}") from e

    def close(self):
        if self._sftp is not None:
            try: self._sftp.close()
            except Exception: pass
            self._sftp = None
        if self._transport is not None:
            try: self._transport.close()
            except Exception: pass
            self._transport = None


# ─────────────────────────────────────────────────────────────────────
# Dropbox
# ─────────────────────────────────────────────────────────────────────

class DropboxBackend:
    """Uses the Dropbox HTTP SDK.

    Auth: prefers the refresh-token path
    (``app_key`` + ``app_secret`` + ``refresh_token``) so the SDK can mint
    a short-lived access token on every call. Falls back to a raw
    ``oauth_token`` for legacy targets created before Dropbox flipped to
    short-lived-only tokens in Sept 2021; those targets will expire every
    4 hours and the operator needs to upgrade via the Edit page.

    We always normalize the remote path to start with "/" because
    Dropbox rejects relative paths. The 150 MB chunked-upload threshold
    is the SDK's documented cutoff where ``files_upload`` stops being
    safe; below it we use the simple one-shot call, above it
    ``files_upload_session_*``.
    """
    CHUNK = 8 * 1024 * 1024
    SIMPLE_UPLOAD_LIMIT = 150 * 1024 * 1024

    def __init__(self, oauth_token=None, app_key=None, app_secret=None,
                 refresh_token=None, remote_path="/"):
        self.token = oauth_token or None
        self.app_key = app_key or None
        self.app_secret = app_secret or None
        self.refresh_token = refresh_token or None
        self.remote_path = self._normalize(remote_path)
        self._dbx = None

    @staticmethod
    def _normalize(p):
        p = (p or "/").strip()
        if not p.startswith("/"):
            p = "/" + p
        # Dropbox does not want a trailing slash on a folder when joining;
        # collapse "//foo" -> "/foo" and strip trailing "/" (except root).
        while "//" in p:
            p = p.replace("//", "/")
        if len(p) > 1 and p.endswith("/"):
            p = p[:-1]
        return p

    def open(self):
        try:
            import dropbox
        except ImportError as e:
            raise BackendError("Dropbox backend requires the 'dropbox' package") from e
        try:
            # Patch urllib3's family selector while the SDK constructs its
            # HTTP pool — that pool gets reused for all subsequent calls
            # on this client, so v4-only resolution sticks.
            with _prefer_ipv4():
                # Refresh-token path (new targets): SDK auto-mints a
                # fresh short-lived access token on every call using the
                # app credentials + refresh token. No 4-hour expiry pain.
                if self.refresh_token and self.app_key and self.app_secret:
                    self._dbx = dropbox.Dropbox(
                        oauth2_refresh_token=self.refresh_token,
                        app_key=self.app_key,
                        app_secret=self.app_secret,
                        timeout=60,
                    )
                elif self.token:
                    # Legacy raw-token path — kept for pre-2.1.11 targets.
                    self._dbx = dropbox.Dropbox(self.token, timeout=60)
                else:
                    raise BackendError(
                        "Dropbox target is missing credentials. Edit the "
                        "target and supply App key + App secret + an OAuth "
                        "authorization code to upgrade to a refresh-token "
                        "configuration.")
                # check_user is the cheapest authenticated call — fails fast
                # if the token was revoked. Also forces the pool to open
                # its first connection while the patch is active.
                self._dbx.users_get_current_account()
        except dropbox.exceptions.AuthError as e:
            raise BackendError(f"Dropbox auth failed: {e}") from e
        except Exception as e:
            raise BackendError(f"Dropbox connect failed: {e}") from e

    def _full(self, name):
        return f"{self.remote_path}/{name}" if self.remote_path != "/" else f"/{name}"

    def put(self, local_path, remote_name):
        import dropbox
        from dropbox.files import WriteMode, CommitInfo, UploadSessionCursor
        full = self._full(remote_name)
        size = os.path.getsize(local_path)
        try:
            with _prefer_ipv4(), open(local_path, "rb") as f:
                if size <= self.SIMPLE_UPLOAD_LIMIT:
                    self._dbx.files_upload(f.read(), full, mode=WriteMode.overwrite)
                    return
                # Chunked session for large archives.
                session = self._dbx.files_upload_session_start(f.read(self.CHUNK))
                cursor = UploadSessionCursor(session_id=session.session_id, offset=f.tell())
                commit = CommitInfo(path=full, mode=WriteMode.overwrite)
                while f.tell() < size - self.CHUNK:
                    self._dbx.files_upload_session_append_v2(f.read(self.CHUNK), cursor)
                    cursor.offset = f.tell()
                self._dbx.files_upload_session_finish(f.read(self.CHUNK), cursor, commit)
        except dropbox.exceptions.ApiError as e:
            raise BackendError(f"Dropbox upload failed: {e}") from e
        except Exception as e:
            raise BackendError(f"Dropbox upload failed: {e}") from e

    def list(self) -> list[RemoteFile]:
        import dropbox
        out: list[RemoteFile] = []
        path = "" if self.remote_path == "/" else self.remote_path
        try:
            with _prefer_ipv4():
                res = self._dbx.files_list_folder(path)
                while True:
                    for entry in res.entries:
                        if not hasattr(entry, "size"):
                            continue  # folder
                        if not _is_export_name(entry.name):
                            continue
                        mtime = entry.client_modified.timestamp() if entry.client_modified else 0
                        out.append(RemoteFile(name=entry.name, size=entry.size, mtime=mtime))
                    if not res.has_more:
                        break
                    res = self._dbx.files_list_folder_continue(res.cursor)
        except dropbox.exceptions.ApiError as e:
            # If the folder doesn't exist yet, that's not an error —
            # just return empty. The first upload will create it.
            from dropbox.files import ListFolderError
            err = getattr(e, "error", None)
            if isinstance(err, ListFolderError) and err.is_path() and err.get_path().is_not_found():
                return []
            raise BackendError(f"Dropbox list failed: {e}") from e
        except Exception as e:
            raise BackendError(f"Dropbox list failed: {e}") from e
        out.sort(key=lambda r: r.name, reverse=True)
        return out

    def delete(self, remote_name):
        import dropbox
        if not _is_export_name(remote_name):
            raise BackendError(f"refusing to delete non-export file {remote_name!r}")
        try:
            with _prefer_ipv4():
                self._dbx.files_delete_v2(self._full(remote_name))
        except dropbox.exceptions.ApiError as e:
            raise BackendError(f"Dropbox delete failed: {e}") from e

    def fetch(self, remote_name, local_path):
        import dropbox
        try:
            with _prefer_ipv4():
                self._dbx.files_download_to_file(local_path, self._full(remote_name))
        except dropbox.exceptions.ApiError as e:
            raise BackendError(f"Dropbox fetch failed: {e}") from e

    def close(self):
        if self._dbx is not None:
            try: self._dbx.close()
            except Exception: pass
            self._dbx = None


# ─────────────────────────────────────────────────────────────────────
# TS Pro Backup (off-site, end-to-end encrypted HTTP destination)
# ─────────────────────────────────────────────────────────────────────

class TSProBackupBackend:
    """Push backups to a TS Pro Backup server over its ``/api/v1`` API.

    Unlike the other backends this one is **end-to-end encrypted**: the
    destination issues this site an X25519 keypair and we encrypt every
    archive to the server's *public* key (``app.pubkey``, ``TSPEPK01``)
    before upload, so the server only ever stores ciphertext it cannot
    read. Only the operator's private key — entered at restore time, never
    sent here — can decrypt. ``fetch`` therefore returns ciphertext; the
    restore flow decrypts it with the private key.

    The server identifies backups by integer id, not filename, so ``list``
    caches a name→id map that ``delete`` reuses. Retention is primarily the
    server's job (its per-site GFS policy); the scheduler's ``retain_count``
    acts as a secondary cap via ``delete``.
    """

    def __init__(self, api_base_url, api_key, public_key, scope="full", timeout=120,
                 callback_url="", restore_token="", restore_enabled=False):
        self.base = (api_base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.public_key = public_key or ""
        self.scope = scope or "full"
        self.timeout = timeout
        # Remote-restore pairing: published to the server in open() so it
        # knows how to push a backup back to us and how to authenticate it.
        self.callback_url = (callback_url or "").rstrip("/")
        self.restore_token = restore_token or ""
        self.restore_enabled = bool(restore_enabled)
        self._sess = None
        self._ids = {}  # remote_name -> backup id, populated by list()
        # Chunked-upload capability, learned from /ping in open(). When the
        # encrypted archive exceeds one chunk we split it so a body-size-
        # limited proxy (e.g. Cloudflare's 100 MiB cap) can't reject it.
        self._chunked = False
        self._chunk_mb = 90

    # ── helpers ────────────────────────────────────────────────────
    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"}

    def _url(self, path):
        return f"{self.base}{path}"

    def _check(self, resp, what):
        if resp.status_code in (200, 201):
            return
        try:
            msg = resp.json().get("error") or resp.text
        except Exception:  # noqa: BLE001
            msg = resp.text
        if resp.status_code in (401, 403):
            raise BackendError(f"TS Pro Backup auth failed: {msg}")
        raise BackendError(f"TS Pro Backup {what} failed (HTTP {resp.status_code}): {msg}")

    # ── lifecycle ──────────────────────────────────────────────────
    def open(self):
        import requests
        if not self.base:
            raise BackendError("TS Pro Backup: no API URL configured")
        self._sess = requests.Session()
        try:
            r = self._sess.get(self._url("/ping"), headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise BackendError(f"TS Pro Backup connect failed: {e}") from e
        self._check(r, "ping")
        caps = r.json()
        self._chunked = bool(caps.get("chunked_upload"))
        try:
            self._chunk_mb = max(1, int(caps.get("max_chunk_mb") or 90))
        except (TypeError, ValueError):
            self._chunk_mb = 90
        server_pub = caps.get("e2ee_public_key")
        # Adopt the server's key if we don't have one yet; refuse to upload
        # to a *different* key than the admin confirmed (a silent server-side
        # rotation would make backups undecryptable with the stored private
        # key) — the admin must re-confirm via "Test connection".
        if server_pub:
            if not self.public_key:
                self.public_key = server_pub
            elif server_pub != self.public_key:
                raise BackendError(
                    "TS Pro Backup: the server's encryption key changed since this "
                    "target was configured. Re-test the connection to adopt the new "
                    "key — and keep the old private key to restore existing backups.")
        if not self.public_key:
            raise BackendError(
                "TS Pro Backup: server provided no encryption key. Rotate the site's "
                "keypair in the backup server console, then re-test the connection.")

        # Publish (or clear) our remote-restore pairing if the server supports
        # it. Best-effort: a registration failure must never block a backup —
        # remote restore is a recovery convenience, not part of the upload.
        if caps.get("remote_restore"):
            payload = {"restore_enabled": bool(self.restore_enabled and self.callback_url and self.restore_token)}
            if payload["restore_enabled"]:
                payload["callback_url"] = self.callback_url
                payload["restore_token"] = self.restore_token
            try:
                self._sess.post(self._url("/register"), headers=self._headers(),
                                json=payload, timeout=self.timeout)
            except requests.RequestException:
                pass

    def put(self, local_path, remote_name):
        import os as _os
        import tempfile
        from . import pubkey
        enc_path = None
        try:
            # Encrypt alongside the source zip (on the data volume), not
            # /tmp — the ciphertext is ~the size of the full archive and
            # /tmp is often a small tmpfs / constrained overlay.
            _scratch = _os.environ.get("TSP_TMP_DIR") or _os.path.dirname(_os.path.abspath(local_path)) or None
            fd, enc_path = tempfile.mkstemp(prefix="tsp-e2ee-", suffix=pubkey.EXT, dir=_scratch)
            _os.close(fd)
            try:
                pubkey.encrypt_to_pubkey(local_path, enc_path, self.public_key)
            except pubkey.E2EEKeyError as e:
                raise BackendError(f"TS Pro Backup: bad encryption key — {e}") from e
            upload_name = remote_name + pubkey.EXT
            chunk_bytes = self._chunk_mb * 1024 * 1024
            # Chunk when the server supports it and the ciphertext exceeds a
            # single chunk; otherwise one request is simpler.
            if self._chunked and _os.path.getsize(enc_path) > chunk_bytes:
                self._put_chunked(enc_path, upload_name, chunk_bytes)
            else:
                self._put_single(enc_path, upload_name)
        finally:
            if enc_path and _os.path.exists(enc_path):
                try: _os.unlink(enc_path)
                except OSError: pass

    def _put_single(self, enc_path, upload_name):
        try:
            with open(enc_path, "rb") as fh:
                r = self._sess.post(
                    self._url("/backups"),
                    headers=self._headers(),
                    data={"scope": self.scope},
                    files={"file": (upload_name, fh, "application/octet-stream")},
                    timeout=None,  # large archives; no read timeout
                )
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"TS Pro Backup upload failed: {e}") from e
        self._check(r, "upload")

    def _put_chunked(self, enc_path, upload_name, chunk_bytes):
        """Split the ciphertext into <=chunk_bytes parts, POST each to
        /backups/chunk, then /backups/finalize to reassemble + ingest.
        Each request stays under the fronting proxy's body limit."""
        import math
        import os as _os
        import uuid
        total = os.path.getsize(enc_path)
        n = max(1, math.ceil(total / chunk_bytes))
        upload_id = str(uuid.uuid4())
        try:
            with open(enc_path, "rb") as fh:
                for index in range(n):
                    blob = fh.read(chunk_bytes)
                    if not blob:
                        break
                    r = self._sess.post(
                        self._url("/backups/chunk"),
                        headers=self._headers(),
                        data={"upload_id": upload_id, "chunk_index": index, "total_chunks": n},
                        files={"chunk": (f"{index:08d}.bin", blob, "application/octet-stream")},
                        timeout=None,
                    )
                    self._check(r, f"chunk {index + 1}/{n}")
            r = self._sess.post(
                self._url("/backups/finalize"),
                headers=self._headers(),
                data={"upload_id": upload_id, "scope": self.scope,
                      "filename": upload_name, "total_chunks": n},
                timeout=None,
            )
        except BackendError:
            raise
        except Exception as e:  # noqa: BLE001
            raise BackendError(f"TS Pro Backup chunked upload failed: {e}") from e
        self._check(r, "finalize")

    def list(self) -> list[RemoteFile]:
        import requests
        try:
            r = self._sess.get(self._url("/backups"), headers=self._headers(),
                               params={"scope": self.scope}, timeout=self.timeout)
        except requests.RequestException as e:
            raise BackendError(f"TS Pro Backup list failed: {e}") from e
        self._check(r, "list")
        out, self._ids = [], {}
        for b in r.json().get("backups", []):
            name = b.get("name") or f"backup-{b['id']}"
            self._ids[name] = b["id"]
            out.append(RemoteFile(name=name, size=b.get("stored_size") or b.get("size") or 0, mtime=0))
        out.sort(key=lambda rf: rf.name, reverse=True)
        return out

    def delete(self, remote_name):
        import requests
        bid = self._ids.get(remote_name)
        if bid is None:
            # Refresh the map once in case delete was called without a prior list.
            self.list()
            bid = self._ids.get(remote_name)
        if bid is None:
            raise BackendError(f"TS Pro Backup: no stored backup named {remote_name!r}")
        try:
            r = self._sess.delete(self._url(f"/backups/{bid}"), headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise BackendError(f"TS Pro Backup delete failed: {e}") from e
        self._check(r, "delete")

    def fetch(self, remote_name, local_path):
        """Download the stored (still-encrypted) archive. The restore flow
        decrypts it with the operator's private key."""
        import requests
        bid = self._ids.get(remote_name)
        if bid is None:
            self.list()
            bid = self._ids.get(remote_name)
        if bid is None:
            raise BackendError(f"TS Pro Backup: no stored backup named {remote_name!r}")
        try:
            with self._sess.get(self._url(f"/backups/{bid}/download"), headers=self._headers(),
                                stream=True, timeout=None) as r:
                self._check(r, "fetch")
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
        except requests.RequestException as e:
            raise BackendError(f"TS Pro Backup fetch failed: {e}") from e

    def close(self):
        if self._sess is not None:
            try: self._sess.close()
            except Exception: pass
            self._sess = None


# ─────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────

def make_backend(target):
    """Build a backend instance from a BackupTarget row.

    Decrypts credentials with the app's Fernet key at call time — we
    deliberately don't cache the plaintext on the model so a credential
    rotation takes effect the next time the scheduler picks the target up.
    """
    from .crypto import decrypt
    kind = target.kind
    if kind == "ftp":
        return FTPBackend(
            host=target.host,
            port=target.port or (21 if not target.use_tls else 21),
            username=target.username or "",
            password=decrypt(target.password_enc) if target.password_enc else "",
            remote_path=target.remote_path or "/",
            use_tls=bool(target.use_tls),
        )
    if kind == "sftp":
        return SFTPBackend(
            host=target.host,
            port=target.port or 22,
            username=target.username or "",
            password=decrypt(target.password_enc) if target.password_enc else None,
            private_key=decrypt(target.private_key_enc) if target.private_key_enc else None,
            remote_path=target.remote_path or "/",
        )
    if kind == "dropbox":
        return DropboxBackend(
            oauth_token=decrypt(target.oauth_token_enc) if target.oauth_token_enc else "",
            app_key=target.app_key or None,
            app_secret=decrypt(target.app_secret_enc) if target.app_secret_enc else None,
            refresh_token=decrypt(target.refresh_token_enc) if target.refresh_token_enc else None,
            remote_path=target.remote_path or "/",
        )
    if kind == "tspro_backup":
        return TSProBackupBackend(
            api_base_url=target.api_base_url or "",
            api_key=decrypt(target.api_key_enc) if target.api_key_enc else "",
            public_key=target.e2ee_public_key or "",
            callback_url=target.public_url or "",
            restore_token=target.restore_token if target.allow_remote_restore else "",
            restore_enabled=bool(target.allow_remote_restore),
        )
    raise BackendError(f"unknown backup kind {kind!r}")
