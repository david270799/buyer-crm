"""/server (the owner, 25.10.2026): how loaded the server is — memory, disk,
processor — to plan what else fits on it. Read-only, from /proc and the disk;
nothing is changed. In a container the numbers are what the container sees
(on the owner's LXD container «davron» that is its own 4 GB)."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from crm.services.common import Actor, require_admin

SMALL_APP_MB = 150  # a small bot or site in Docker, for the «сколько ещё влезет» estimate


@dataclass(frozen=True)
class ServerStatus:
    cpus: int
    load: tuple[float, float, float]  # 1, 5, 15 minutes
    mem_total_mb: int | None
    mem_available_mb: int | None
    disk_total_gb: float
    disk_free_gb: float
    crm_mb: int | None  # this CRM process
    uptime_s: int | None
    cpu_temp_c: float | None = None  # processor sensor (hwmon), if the container sees it

    @property
    def mem_used_mb(self) -> int | None:
        if self.mem_total_mb is None or self.mem_available_mb is None:
            return None
        return self.mem_total_mb - self.mem_available_mb

    @property
    def small_apps_left(self) -> int | None:
        """Small apps that still fit, keeping 500 MB spare for the system."""
        if self.mem_available_mb is None:
            return None
        return max(0, (self.mem_available_mb - 500) // SMALL_APP_MB)


def parse_meminfo(text: str) -> tuple[int | None, int | None]:
    """MemTotal and MemAvailable from /proc/meminfo, in MB."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[name.strip()] = int(parts[0]) // 1024  # kB → MB
    return values.get("MemTotal"), values.get("MemAvailable")


def parse_rss_mb(status_text: str) -> int | None:
    """VmRSS of a process from /proc/<pid>/status, in MB."""
    for line in status_text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            return int(parts[1]) // 1024 if len(parts) > 1 and parts[1].isdigit() else None
    return None


# Processor sensors first (AMD, Intel, ARM boards); acpitz is the board, a last resort.
_CPU_SENSORS = ("k10temp", "zenpower", "coretemp", "cpu_thermal", "soc_thermal", "acpitz")


def cpu_temperature(hwmon_root: Path | str = "/sys/class/hwmon") -> float | None:
    """Processor temperature in °C from /sys/class/hwmon (millidegrees in temp1_input)."""
    found: dict[str, float] = {}
    for sensor in sorted(Path(hwmon_root).glob("hwmon*")):
        name = _read(str(sensor / "name")).strip()
        raw = _read(str(sensor / "temp1_input")).strip()
        if name in _CPU_SENSORS and raw.lstrip("-").isdigit() and name not in found:
            found[name] = int(raw) / 1000
    for name in _CPU_SENSORS:
        if name in found:
            return round(found[name], 1)
    return None


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def read_status(actor: Actor, data_dir: Path | str = "/") -> ServerStatus:
    require_admin(actor)
    total, available = parse_meminfo(_read("/proc/meminfo"))
    try:
        load = os.getloadavg()
    except OSError:
        load = (0.0, 0.0, 0.0)
    disk = shutil.disk_usage(data_dir if Path(data_dir).exists() else "/")
    uptime = _read("/proc/uptime").split()
    return ServerStatus(
        cpus=os.cpu_count() or 1,
        load=(round(load[0], 2), round(load[1], 2), round(load[2], 2)),
        mem_total_mb=total,
        mem_available_mb=available,
        disk_total_gb=round(disk.total / 1024**3, 1),
        disk_free_gb=round(disk.free / 1024**3, 1),
        crm_mb=parse_rss_mb(_read("/proc/self/status")),
        uptime_s=int(float(uptime[0])) if uptime else None,
        cpu_temp_c=cpu_temperature(),
    )
