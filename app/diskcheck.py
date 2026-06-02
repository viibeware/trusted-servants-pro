# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lightweight disk-space watchdog.

Surfaces an admin warning (banner + a throttled log line) when the
filesystem holding the data volume — or the host root — crosses a usage
threshold, so an operator gets runway to act *before* backups, uploads,
or image pulls start failing with "no space left on device".

The check is a couple of ``statvfs`` syscalls; results are cached briefly
so the per-request context processor that calls it stays cheap, and the
log warning is rate-limited so a full disk doesn't flood the log.
"""
import os
import shutil
import time
import logging

logger = logging.getLogger(__name__)

WARN_THRESHOLD = 0.85          # fraction used at or above which we warn
_CACHE_TTL = 300               # seconds a computed result is reused
_LOG_INTERVAL = 3600           # min seconds between repeated log warnings
_GIB = 1024 ** 3

# Module-level cache. Each gunicorn worker keeps its own — fine; the cost
# is at most one log line per worker per _LOG_INTERVAL.
_cache = {"at": 0.0, "result": None}
_last_log_at = 0.0


def _probe(data_dir, threshold):
    """Return the worst at/over-threshold filesystem as a dict, or None.

    Checks the data volume and the host root, de-duplicated by device id
    (on most installs they're the same physical disk), and reports the
    fullest one.
    """
    worst = None
    seen_devs = set()
    for label, path in (("data volume", data_dir), ("server disk", "/")):
        if not path:
            continue
        try:
            dev = os.stat(path).st_dev
        except OSError:
            continue
        if dev in seen_devs:
            continue
        seen_devs.add(dev)
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        if not usage.total:
            continue
        frac = usage.used / usage.total
        if frac >= threshold:
            cand = {
                "label": label,
                "percent": int(round(frac * 100)),
                "free_gb": round(usage.free / _GIB, 1),
                "total_gb": round(usage.total / _GIB, 1),
            }
            if worst is None or cand["percent"] > worst["percent"]:
                worst = cand
    return worst


def disk_warning(data_dir, threshold=WARN_THRESHOLD, _now=None):
    """Cached, log-throttled disk check for the request context processor.

    Returns ``{label, percent, free_gb, total_gb}`` when a monitored
    filesystem is at/over ``threshold``, else ``None``. Safe to call on
    every request: the underlying probe runs at most once per
    ``_CACHE_TTL`` seconds.
    """
    global _last_log_at
    now = _now if _now is not None else time.time()
    if _cache["at"] and now - _cache["at"] < _CACHE_TTL:
        # Reuse within the TTL. A live warning is re-probed once the TTL
        # lapses, so the banner clears promptly after space is freed.
        return _cache["result"]
    result = _probe(data_dir, threshold)
    _cache["at"] = now
    _cache["result"] = result
    if result is not None and now - _last_log_at >= _LOG_INTERVAL:
        _last_log_at = now
        logger.warning(
            "disk space low: %s is %d%% full (%.1f GB free of %.1f GB) — "
            "free space before backups, uploads, or updates fail",
            result["label"], result["percent"], result["free_gb"], result["total_gb"],
        )
    return result
