# SPDX-License-Identifier: AGPL-3.0-or-later
"""Video Streamer engine.

Spawns an ffmpeg subprocess that ingests the admin-configured source
(v4l2 device, RTSP URL, HTTP URL, or local file) and writes HLS
segments to ``$TSP_DATA_DIR/stream/``. The public ``/videostreamer``
viewer page then plays the manifest via hls.js.

Why HLS rather than MJPEG/WebRTC:
  - HLS supports audio. MJPEG does not.
  - HLS scales: many viewers share the same .ts files.
  - HLS is server-stateless once segments are written, so a single
    long-running ffmpeg process feeds any number of viewers without
    per-client work in Python.
  - WebRTC would beat HLS on latency but requires an SFU + signaling
    stack that's well outside the scope of a Flask app.

The trade-off is ~5–10 s glass-to-glass latency from HLS's segment
duration. The Stream Manager keeps segment duration short (2 s) and
the playlist small (6 entries) to minimize this without going to LL-HLS.
"""
import os
import shlex
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime


# HLS output knobs. ``hls_time`` is the target segment length in
# seconds; ``hls_list_size`` is how many segments the live playlist
# carries. The pair gives ~12 s of buffered content for late-joining
# viewers while keeping latency low.
_HLS_SEGMENT_SECONDS = 2
_HLS_LIST_SIZE = 6

# Output directory layout (relative to TSP_DATA_DIR):
#   stream/
#     stream.m3u8        — live playlist
#     seg_NNN.ts         — segments (auto-cleaned by ffmpeg via
#                          hls_flags=delete_segments)
_STREAM_SUBDIR = "stream"
_MANIFEST_NAME = "stream.m3u8"

# Allowed source types — same set the admin form's <select> emits.
#
# ``browser`` is the admin's own webcam, streamed in via a WebSocket
# ingest (see ``start_pipe`` below + the WS route in ``app/routes.py``).
# It's the only source where ffmpeg reads from ``stdin`` rather than
# a path, and where the lifecycle is driven by the WebSocket rather
# than by the Start/Stop buttons in the admin form.
SOURCE_TYPES = ("device", "rtsp", "http", "file", "browser")

# Soft lock — keeps two near-simultaneous start/stop calls from racing
# on the manager's internal state. The ffmpeg process itself is the
# canonical "is it running?" signal.
_state_lock = threading.RLock()


class _StreamManager:
    """Singleton — one logical stream per portal.

    Holds a reference to the current ffmpeg ``Popen`` so the admin
    page can poll its status (alive vs exited) and stop it cleanly.
    All public methods are safe to call from multiple gunicorn workers
    (the lock keeps in-process callers consistent; cross-worker
    coordination falls back on the ``status`` column in ``VideoStream``
    being updated by whichever worker owns the process).
    """

    def __init__(self):
        self._proc = None
        self._stderr_tail = []  # bounded log of recent ffmpeg stderr lines
        self._stderr_thread = None
        self._data_dir = None

    # ── public API ────────────────────────────────────────────────

    def configure(self, data_dir):
        """Stash the absolute path to ``$TSP_DATA_DIR`` so we can
        derive the HLS output directory without depending on Flask's
        ``current_app`` proxy from helper threads."""
        self._data_dir = data_dir

    @property
    def stream_dir(self):
        """Filesystem directory the manifest + segments live in."""
        base = self._data_dir or os.path.abspath(
            os.environ.get("TSP_DATA_DIR", "./data"))
        return os.path.join(base, _STREAM_SUBDIR)

    @property
    def manifest_path(self):
        return os.path.join(self.stream_dir, _MANIFEST_NAME)

    def is_running(self):
        """True iff the ffmpeg subprocess is alive — in this worker."""
        with _state_lock:
            return self._proc is not None and self._proc.poll() is None

    def is_running_pid(self, pid):
        """Cross-worker live-process probe. Gunicorn spawns ffmpeg from
        a single worker; if a peer worker handles a later status / stop
        request, it can't see ``self._proc`` because the singleton is
        per-process. This helper consults the OS via ``os.kill(pid, 0)``
        so any worker can verify whether the PID persisted in the DB
        is still alive."""
        if not pid:
            return False
        try:
            os.kill(int(pid), 0)
            return True
        except (ProcessLookupError, OSError, ValueError):
            return False

    def current_pid(self):
        with _state_lock:
            if self._proc is None:
                return None
            return self._proc.pid

    def recent_log(self):
        """Return the last ~60 lines of ffmpeg stderr. Useful for the
        admin page when a start attempt fails — ffmpeg prints the
        reason ("No such file or directory", "Permission denied",
        "Operation not permitted on device") right before exiting."""
        with _state_lock:
            return list(self._stderr_tail)

    def start(self, stream):
        """Spawn ffmpeg for the given ``VideoStream`` row.

        Returns ``(ok: bool, message: str)``. On failure, ``message``
        is a human-readable reason suitable for flashing back to the
        admin. On success, the manager owns the new subprocess and
        ``is_running()`` will return True.
        """
        with _state_lock:
            if self.is_running():
                return (False, "Stream is already running")
            # Cross-worker: a peer gunicorn worker might already own
            # the live ffmpeg. Refuse to start a second one against
            # the same output directory — they'd race on segment
            # filenames and the playlist would corrupt.
            if self.is_running_pid(stream.pid):
                return (False, f"Stream is already running (pid {stream.pid})")

            if not stream.source_path:
                return (False, "Configure a source path/URL before starting")
            if stream.source_type not in SOURCE_TYPES:
                return (False, f"Unsupported source type: {stream.source_type}")

            if not _have_ffmpeg():
                return (False,
                        "ffmpeg is not installed in this container. "
                        "Rebuild the image or install ffmpeg on the host.")

            os.makedirs(self.stream_dir, exist_ok=True)
            # Sweep stale segments from a previous run so the new
            # playlist starts clean (otherwise hls.js may try to play
            # segments that no longer match the current source).
            _purge_stream_dir(self.stream_dir)

            cmd = _build_ffmpeg_command(stream, self.stream_dir)
            try:
                # ``start_new_session=True`` puts ffmpeg in its own
                # process group so a clean stop signals just the
                # subprocess (and any helper it forks) — not the
                # gunicorn worker we're running inside.
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except OSError as e:
                return (False, f"Failed to spawn ffmpeg: {e}")
            self._stderr_tail = []
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, args=(self._proc,), daemon=True)
            self._stderr_thread.start()
            return (True, f"Stream started (pid {self._proc.pid})")

    def stop(self, stream=None):
        """Terminate the ffmpeg subprocess. Returns ``(ok, message)``.
        Idempotent — calling stop on an already-stopped stream returns
        a success result.

        ``stream`` is the ``VideoStream`` row. If the in-process
        subprocess reference isn't set (because a peer gunicorn worker
        spawned it), we fall back to signalling the PID the row
        persisted at start time. This is what lets the admin's Stop
        button work regardless of which worker handles the click."""
        with _state_lock:
            # Path 1 — we own the subprocess directly. Best signal
            # quality (we know exactly when it exits, and we have its
            # stderr).
            if self.is_running():
                proc = self._proc
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                except (ProcessLookupError, PermissionError):
                    pass
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError):
                        pass
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                        except (ProcessLookupError, PermissionError):
                            pass
                        proc.wait()
                self._proc = None
                _drop_manifest(self.stream_dir)
                return (True, "Stream stopped")

            # Path 2 — cross-worker fallback. A peer worker started
            # ffmpeg; we only know its PID via the DB row. Signal the
            # process group there.
            persisted_pid = getattr(stream, "pid", None) if stream else None
            if self.is_running_pid(persisted_pid):
                try:
                    pgid = os.getpgid(int(persisted_pid))
                    os.killpg(pgid, signal.SIGINT)
                except (ProcessLookupError, PermissionError, OSError):
                    pass
                # Brief wait so the next status read shows the
                # process actually gone.
                for _ in range(6):
                    if not self.is_running_pid(persisted_pid):
                        break
                    time.sleep(0.5)
                if self.is_running_pid(persisted_pid):
                    try:
                        os.killpg(os.getpgid(int(persisted_pid)), signal.SIGTERM)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                if self.is_running_pid(persisted_pid):
                    try:
                        os.killpg(os.getpgid(int(persisted_pid)), signal.SIGKILL)
                    except (ProcessLookupError, PermissionError, OSError):
                        pass
                _drop_manifest(self.stream_dir)
                return (True, "Stream stopped (cross-worker)")

            _drop_manifest(self.stream_dir)
            self._proc = None
            return (True, "Stream is already stopped")

    def start_pipe(self, stream):
        """Spawn ffmpeg in pipe-input mode for browser-camera ingest.

        Differs from ``start()`` in that ffmpeg reads its input from
        ``stdin`` (a webm stream produced by the browser's
        ``MediaRecorder``) rather than from a path/URL. The HLS output
        side is identical, so once segments start landing in
        ``stream_dir`` the existing public viewer plays them without
        any further changes.

        Returns ``(ok, message)``.
        """
        with _state_lock:
            if self.is_running():
                return (False, "Stream is already running")
            if self.is_running_pid(stream.pid):
                return (False, f"Stream is already running (pid {stream.pid})")
            if not _have_ffmpeg():
                return (False, "ffmpeg is not installed in this container.")

            os.makedirs(self.stream_dir, exist_ok=True)
            _purge_stream_dir(self.stream_dir)

            cmd = _build_pipe_ffmpeg_command(stream, self.stream_dir)
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except OSError as e:
                return (False, f"Failed to spawn ffmpeg: {e}")
            self._stderr_tail = []
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, args=(self._proc,), daemon=True)
            self._stderr_thread.start()
            return (True, f"Pipe mode started (pid {self._proc.pid})")

    def write_chunk(self, data):
        """Forward a webm chunk from the WebSocket into ffmpeg's stdin.
        Returns True on success, False if the pipe is no longer
        writable (ffmpeg crashed or stdin was closed)."""
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdin.closed:
            return False
        if proc.poll() is not None:
            return False
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def close_pipe(self):
        """Close ffmpeg's stdin so it flushes the trailers and exits
        cleanly. Called when the WebSocket disconnects."""
        with _state_lock:
            proc = self._proc
            if proc and proc.stdin and not proc.stdin.closed:
                try:
                    proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            # Give ffmpeg a moment to flush, then force-stop if it
            # doesn't exit on its own.
            if proc:
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.stop()

    def status_snapshot(self):
        """Return a small dict the admin page polls. ``running`` is the
        live process check; the rest is informational."""
        with _state_lock:
            running = self.is_running()
            pid = self._proc.pid if self._proc else None
            exit_code = None
            if self._proc is not None and not running:
                exit_code = self._proc.returncode
            return {
                "running": running,
                "pid": pid,
                "exit_code": exit_code,
                "manifest_exists": os.path.exists(self.manifest_path),
                "log_tail": list(self._stderr_tail[-12:]),
            }

    # ── internals ────────────────────────────────────────────────

    def _drain_stderr(self, proc):
        """Read ffmpeg's stderr line-by-line and keep the last 200
        lines in a bounded list. ffmpeg is verbose; we only need a
        snippet for diagnostics."""
        try:
            for raw in iter(proc.stderr.readline, b""):
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\n")
                with _state_lock:
                    self._stderr_tail.append(line)
                    if len(self._stderr_tail) > 200:
                        del self._stderr_tail[: len(self._stderr_tail) - 200]
        except Exception:  # noqa: BLE001 — never let the drain thread crash boot
            return


# ── module-level singleton + helpers ─────────────────────────────

_manager = _StreamManager()


def get_manager():
    return _manager


def _have_ffmpeg():
    return shutil.which("ffmpeg") is not None


def _build_ffmpeg_command(stream, out_dir):
    """Translate a ``VideoStream`` row into an ffmpeg argv.

    Source dispatch:
      - ``device``   → ``-f v4l2 -i <path>`` (Linux webcams, OBS Virtual Cam)
      - ``rtsp``     → ``-rtsp_transport tcp -i <url>``
      - ``http``     → ``-i <url>`` (works with HTTP MJPEG / progressive video)
      - ``file``     → ``-re -i <path>`` (paces playback at real-time so
                       the HLS clock matches wall-clock)

    Output is always HLS with H.264 video and optional AAC audio. We
    use ``-preset veryfast`` to keep CPU low — webcam streaming on a
    typical VPS won't tolerate the slower-but-better presets.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]

    # Extra input args the admin can paste in for advanced sources
    # (e.g. ``-framerate 30 -video_size 1280x720`` for a v4l2 device).
    if stream.source_input_args:
        try:
            cmd.extend(shlex.split(stream.source_input_args))
        except ValueError:
            # Bad quoting — drop the extras rather than refusing to start.
            pass

    stype = stream.source_type
    path = stream.source_path or ""
    if stype == "device":
        cmd.extend(["-f", "v4l2", "-i", path])
    elif stype == "rtsp":
        cmd.extend(["-rtsp_transport", "tcp", "-i", path])
    elif stype == "http":
        cmd.extend(["-i", path])
    elif stype == "file":
        # ``-re`` paces the file at native frame rate so HLS doesn't
        # try to publish a 90-minute movie in 30 seconds.
        cmd.extend(["-re", "-stream_loop", "-1", "-i", path])
    else:
        # Should be impossible — validated upstream.
        cmd.extend(["-i", path])

    # Video encode. ``-pix_fmt yuv420p`` is the broadly-compatible
    # subsampling Safari + iOS require. ``-g`` (GOP) is tied to the
    # framerate so each HLS segment is a clean keyframe boundary.
    fps = max(5, min(int(stream.framerate or 30), 60))
    w = max(160, min(int(stream.video_width or 1280), 3840))
    h = max(120, min(int(stream.video_height or 720), 2160))
    bitrate = max(200, min(int(stream.bitrate_kbps or 2500), 20000))
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={w}:{h}",
        "-r", str(fps),
        "-g", str(fps * _HLS_SEGMENT_SECONDS),
        "-keyint_min", str(fps * _HLS_SEGMENT_SECONDS),
        "-sc_threshold", "0",
        "-b:v", f"{bitrate}k",
        "-maxrate", f"{bitrate}k",
        "-bufsize", f"{bitrate * 2}k",
    ])

    if stream.include_audio:
        cmd.extend(["-c:a", "aac", "-ar", "44100", "-b:a", "128k"])
    else:
        cmd.append("-an")

    # HLS muxer. ``delete_segments`` keeps the output dir small;
    # ``independent_segments`` is friendlier to byte-range seeking.
    seg_pattern = os.path.join(out_dir, "seg_%05d.ts")
    cmd.extend([
        "-f", "hls",
        "-hls_time", str(_HLS_SEGMENT_SECONDS),
        "-hls_list_size", str(_HLS_LIST_SIZE),
        "-hls_flags", "delete_segments+independent_segments+omit_endlist",
        "-hls_segment_filename", seg_pattern,
        os.path.join(out_dir, _MANIFEST_NAME),
    ])
    return cmd


def _build_pipe_ffmpeg_command(stream, out_dir):
    """ffmpeg command for the browser-camera ingest path.

    Reads a continuous webm stream from stdin (produced by the
    browser's ``MediaRecorder`` with the vp8/opus codecs), then
    transcodes to H.264/AAC HLS so the public viewer's hls.js
    player can play it on every desktop + mobile browser.

    Differences from the path/URL build:
      - Input format is forced (``-f webm``) so ffmpeg doesn't try
        to probe a partial header that may not arrive until a few
        clusters into the stream.
      - ``-fflags +genpts`` synthesises presentation timestamps in
        case the live webm chunks don't carry them — without this
        ffmpeg sometimes emits 'non-monotonic DTS' warnings and the
        HLS segmenter stalls.
      - Audio is included whenever the row says so; if the source
        actually doesn't have audio (admin clicked "Skip audio" in
        getUserMedia) ffmpeg will surface a single warning rather
        than refusing to start.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]
    cmd.extend(["-fflags", "+genpts"])
    cmd.extend(["-f", "webm", "-i", "pipe:0"])

    fps = max(5, min(int(stream.framerate or 30), 60))
    w = max(160, min(int(stream.video_width or 1280), 3840))
    h = max(120, min(int(stream.video_height or 720), 2160))
    bitrate = max(200, min(int(stream.bitrate_kbps or 2500), 20000))
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={w}:{h}",
        "-r", str(fps),
        "-g", str(fps * _HLS_SEGMENT_SECONDS),
        "-keyint_min", str(fps * _HLS_SEGMENT_SECONDS),
        "-sc_threshold", "0",
        "-b:v", f"{bitrate}k",
        "-maxrate", f"{bitrate}k",
        "-bufsize", f"{bitrate * 2}k",
    ])

    if stream.include_audio:
        cmd.extend(["-c:a", "aac", "-ar", "44100", "-b:a", "128k"])
    else:
        cmd.append("-an")

    seg_pattern = os.path.join(out_dir, "seg_%05d.ts")
    cmd.extend([
        "-f", "hls",
        "-hls_time", str(_HLS_SEGMENT_SECONDS),
        "-hls_list_size", str(_HLS_LIST_SIZE),
        "-hls_flags", "delete_segments+independent_segments+omit_endlist",
        "-hls_segment_filename", seg_pattern,
        os.path.join(out_dir, _MANIFEST_NAME),
    ])
    return cmd


def _purge_stream_dir(path):
    """Delete leftover ``.ts`` segments and the previous manifest so a
    new run starts with an empty playlist. Keeps the directory itself
    so the docker volume mapping doesn't have to be re-created."""
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        if name.endswith(".ts") or name.endswith(".m3u8"):
            try:
                os.remove(os.path.join(path, name))
            except OSError:
                continue


def _drop_manifest(path):
    """Remove the live manifest on stop so the public viewer flips to
    its offline state immediately. The .ts segments stay on disk until
    the next start (which calls ``_purge_stream_dir``) — keeping them
    around briefly costs nothing and helps if a viewer's buffer is
    still draining when stop fires."""
    if not path:
        return
    target = os.path.join(path, _MANIFEST_NAME)
    try:
        os.remove(target)
    except OSError:
        pass


def reconcile_status(stream):
    """Sync the ``VideoStream`` row's persisted ``status`` column with
    the live state of the ffmpeg subprocess. Called by the admin page
    before rendering + by the status JSON endpoint so the UI doesn't
    display "running" when the process has crashed in the background.

    Returns the (possibly updated) row so callers can chain.

    Cross-worker note: prefers the in-process subprocess reference
    when this worker owns it (richer signal — exit code + stderr).
    Falls back to an ``os.kill(pid, 0)`` probe against the PID
    persisted on the row so peer workers still report accurate state.
    """
    mgr = get_manager()
    in_process = mgr.is_running()
    cross_worker = mgr.is_running_pid(stream.pid) if not in_process else False
    snap = mgr.status_snapshot()

    if in_process or cross_worker:
        if stream.status != "running":
            stream.status = "running"
        # Keep the persisted PID in lockstep with the live process —
        # whichever worker can see it first wins. If the in-process
        # ref exists, prefer it; otherwise keep whatever was on the
        # row (still pointing at the live PID per the cross-worker
        # probe).
        if in_process and snap.get("pid"):
            stream.pid = snap.get("pid")
    else:
        if stream.status == "running":
            # Process exited on its own; record an error if the exit
            # was non-zero so the admin sees the failure rather than
            # a silent "stopped".
            exit_code = snap.get("exit_code")
            if exit_code not in (None, 0):
                last_log = "\n".join(snap.get("log_tail") or [])
                stream.last_error = (
                    f"ffmpeg exited with code {exit_code}\n{last_log}".strip())
                stream.status = "error"
            else:
                stream.status = "stopped"
            stream.last_stopped_at = datetime.utcnow()
            stream.pid = None
    return stream
