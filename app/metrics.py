# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import platform
import shutil
import time

import psutil

_HOST_PROC = os.environ.get("TSP_HOST_PROC")
_HOST_ETC = os.environ.get("TSP_HOST_ETC")
_HOST_MODE = bool(_HOST_PROC and os.path.isdir(_HOST_PROC))
if _HOST_MODE:
    psutil.PROCFS_PATH = _HOST_PROC


def _read(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _os_pretty_name():
    data = ""
    if _HOST_ETC:
        data = _read(os.path.join(_HOST_ETC, "os-release"))
    if not data:
        data = _read("/etc/os-release")
    for line in data.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.platform()


def _hostname():
    if _HOST_ETC:
        h = _read(os.path.join(_HOST_ETC, "hostname")).strip()
        if h:
            return h
    if _HOST_PROC:
        h = _read(os.path.join(_HOST_PROC, "sys/kernel/hostname")).strip()
        if h:
            return h
    return platform.node()


def _cpu_count():
    if _HOST_PROC:
        data = _read(os.path.join(_HOST_PROC, "cpuinfo"))
        n = sum(1 for line in data.splitlines() if line.startswith("processor"))
        if n:
            return n
    return os.cpu_count() or 1


def _loadavg():
    if _HOST_PROC:
        data = _read(os.path.join(_HOST_PROC, "loadavg")).split()
        if len(data) >= 3:
            try:
                return [float(data[0]), float(data[1]), float(data[2])]
            except ValueError:
                pass
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):
        return [0.0, 0.0, 0.0]


def _disk(disk_path):
    """Usage of the filesystem holding the data volume (``disk_path``),
    falling back to the host root. That's the disk that actually fills —
    DB, uploads, and backups all live on it — so it's what an operator
    needs to watch."""
    for path in (disk_path, "/"):
        if not path:
            continue
        try:
            du = shutil.disk_usage(path)
        except OSError:
            continue
        if du.total:
            return {
                "disk_total": du.total,
                "disk_used": du.used,
                "disk_percent": round(100 * du.used / du.total, 1),
            }
    return {"disk_total": 0, "disk_used": 0, "disk_percent": 0}


def snapshot(disk_path=None):
    vm = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=None)
    return {
        "host_mode": _HOST_MODE,
        "os": _os_pretty_name(),
        "hostname": _hostname(),
        "cpu_count": _cpu_count(),
        "cpu_percent": cpu_pct,
        "load_avg": _loadavg(),
        "memory_total": vm.total,
        "memory_used": vm.total - vm.available,
        "memory_percent": vm.percent,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        **_disk(disk_path),
    }


def prime():
    """Prime psutil.cpu_percent so the first real call returns a real delta."""
    try:
        psutil.cpu_percent(interval=None)
    except Exception:
        pass
