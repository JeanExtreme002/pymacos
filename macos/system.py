# -*- coding: utf-8 -*-

"""
Information about the Mac: macOS version, model, name, uptime, idle time, disks, fonts, heat, lid, camera and microphone use.

::

    macos.system.version()        # '15.6.1'
    macos.system.model()          # 'MacBook Pro'
    macos.system.processor()      # 'Apple M2 Pro'
    macos.system.idle_time()      # datetime.timedelta(seconds=312)

Kernel values come from ``sysctl`` and IOKit directly; the rest from the
commands that ship with macOS.
"""

import ctypes
import json
import os
import platform
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple, Union

from . import _cf, _iokit, _libc, _objc, defaults
from ._libc import pids as _pids
from ._system import framework, require_macos, run as _run
from .errors import CommandError, CommandTimeoutError, MacOSError, NotSupportedError

__all__ = [
    "version",
    "build",
    "model",
    "model_identifier",
    "processor",
    "memory",
    "computer_name",
    "uptime",
    "cpu_usage",
    "MemoryUsage",
    "memory_usage",
    "idle_time",
    "wait_for_idle",
    "wait_for_activity",
    "volumes",
    "eject",
    "mount_image",
    "unmount_image",
    "Update",
    "available_updates",
    "fonts",
    "thermal_state",
    "lid_closed",
    "camera_in_use",
    "microphone_in_use",
    "Volume",
    "ds_store_on_network",
    "set_ds_store_on_network",
    "ds_store_on_usb",
    "set_ds_store_on_usb",
    "keep_windows_on_quit",
    "set_keep_windows_on_quit",
    "battery_percentage_shown",
    "set_show_battery_percentage",
    "save_to_icloud_by_default",
    "set_save_to_icloud_by_default",
    "expanded_save_dialog",
    "set_expanded_save_dialog",
    "clock_format",
    "set_clock_format",
    "measurement_units",
    "set_measurement_units",
    "temperature_unit",
    "set_temperature_unit",
    "open_photos_on_device_connect",
    "set_open_photos_on_device_connect",
    "menu_bar_spacing",
    "set_menu_bar_spacing",
    "MENU_BAR_ITEMS",
    "menu_bar_items",
    "set_menu_bar_items",
    "SecurityStatus",
    "security_status",
    "Process",
    "processes",
    "process",
    "kill",
    "Port",
    "ports",
    "port_owner",
    "Connection",
    "connections",
    "open_files",
    "who_uses",
    "NetworkUsage",
    "network_usage",
    "EnergyUsage",
    "energy_usage",
    "GPUUsage",
    "gpu_usage",
    "DiskHealth",
    "disk_health",
    "CrashReport",
    "crash_reports",
    "LogEntry",
    "logs",
    "USBDevice",
    "usb_devices",
    "StartupItem",
    "startup_items",
]


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_int32)]


def _sysctl(name: str) -> bytes:
    lib = _libc.lib()
    size = ctypes.c_size_t()
    if lib.sysctlbyname(name.encode(), None, ctypes.byref(size), None, 0) != 0:
        raise MacOSError("sysctl {} is not available".format(name))
    buffer = ctypes.create_string_buffer(size.value)
    if lib.sysctlbyname(name.encode(), buffer, ctypes.byref(size), None, 0) != 0:
        raise MacOSError("sysctl {} is not available".format(name))
    return buffer.raw[: size.value]


def _sysctl_str(name: str) -> str:
    return _sysctl(name).rstrip(b"\0").decode("utf-8", "replace")


def version() -> str:
    """The macOS version, e.g. ``'15.6.1'``."""
    require_macos()
    return platform.mac_ver()[0]


def build() -> str:
    """The macOS build number, e.g. ``'24G90'``."""
    return _run(["sw_vers", "-buildVersion"]).strip()


_PROFILER_TIMEOUT = 60.0  # seconds: system_profiler takes a moment, and has hung on some Macs


@lru_cache(maxsize=None)
def model() -> str:
    """
    The Mac's marketing name, e.g. ``'MacBook Pro'`` or ``'Mac mini'``.

    Raises :class:`~macos.errors.MacOSError` when macOS doesn't say, as in
    some virtual machines.
    """
    # system_profiler takes a moment, and the answer never changes: cache it (a failure isn't cached).
    output = _run(["system_profiler", "SPHardwareDataType", "-json"], timeout=_PROFILER_TIMEOUT)
    try:
        name = json.loads(output)["SPHardwareDataType"][0]["machine_name"]
    except (ValueError, LookupError, TypeError):
        name = None  # not JSON, or not shaped as expected: a VM, or a later macOS
    if not isinstance(name, str) or not name:
        raise MacOSError("system_profiler didn't tell this Mac's model")
    return name


def model_identifier() -> str:
    """The Mac's model identifier, e.g. ``'Mac14,9'``."""
    return _sysctl_str("hw.model")


def processor() -> str:
    """The processor's name, e.g. ``'Apple M2 Pro'`` or ``'Intel(R) Core(TM) i7-9750H ...'``."""
    return _sysctl_str("machdep.cpu.brand_string")


def memory() -> int:
    """The installed memory (RAM), in bytes."""
    return int.from_bytes(_sysctl("hw.memsize"), "little")


def computer_name() -> str:
    """The name shown in System Settings › General › About (and on the network)."""
    return _run(["scutil", "--get", "ComputerName"]).strip()


def uptime() -> timedelta:
    """How long the Mac has been running since it last started (sleep time included)."""
    boot = _Timeval.from_buffer_copy(_sysctl("kern.boottime")[: ctypes.sizeof(_Timeval)])
    return timedelta(seconds=round(time.time() - (boot.tv_sec + boot.tv_usec / 1e6)))


def idle_time() -> timedelta:
    """
    Time since the last keyboard, mouse or trackpad input.

    Useful to run something only while the user is away::

        if macos.system.idle_time() > timedelta(minutes=10):
            run_heavy_job()
    """
    io = _iokit.lib()
    # IOServiceGetMatchingService consumes the matching dictionary; 0 is the
    # default main port.
    service = io.IOServiceGetMatchingService(0, io.IOServiceMatching(b"IOHIDSystem"))
    if not service:
        raise MacOSError("the IOHIDSystem service is not available")
    try:
        with _cf.owned(_cf.string("HIDIdleTime")) as key:
            value: Optional[int]
            with _cf.owned(io.IORegistryEntryCreateCFProperty(service, key, None, 0)) as ref:
                value = _cf.to_int(ref)
    finally:
        io.IOObjectRelease(service)
    if value is None:
        raise MacOSError("the idle time is not available")
    return timedelta(microseconds=value / 1000)  # nanoseconds


_CPU_LOAD_INFO, _VM_INFO64 = 3, 4  # HOST_CPU_LOAD_INFO, HOST_VM_INFO64


class _VMStatistics(ctypes.Structure):
    """``vm_statistics64``: page counts."""

    natural, counter = ctypes.c_uint32, ctypes.c_uint64
    _fields_ = [
        ("free_count", natural),
        ("active_count", natural),
        ("inactive_count", natural),
        ("wire_count", natural),
        ("zero_fill_count", counter),
        ("reactivations", counter),
        ("pageins", counter),
        ("pageouts", counter),
        ("faults", counter),
        ("cow_faults", counter),
        ("lookups", counter),
        ("hits", counter),
        ("purges", counter),
        ("purgeable_count", natural),
        ("speculative_count", natural),
        ("decompressions", counter),
        ("compressions", counter),
        ("swapins", counter),
        ("swapouts", counter),
        ("compressor_page_count", natural),
        ("throttled_count", natural),
        ("external_page_count", natural),
        ("internal_page_count", natural),
        ("total_uncompressed_pages_in_compressor", counter),
    ]


def _cpu_ticks() -> Tuple[int, int, int, int]:
    """The processor's user, system, idle and nice ticks since startup, all cores together (32-bit counters)."""
    require_macos()
    ticks = (ctypes.c_uint32 * 4)()  # user, system, idle, nice
    count = ctypes.c_uint32(4)
    mach = _libc.lib()
    if mach.host_statistics(mach.mach_host_self(), _CPU_LOAD_INFO, ticks, ctypes.byref(count)) != 0:
        raise MacOSError("could not read the processor load")
    return ticks[0], ticks[1], ticks[2], ticks[3]


def cpu_usage(interval: float = 0.5) -> float:
    """
    How busy the processor is, from 0.0 (idle) to 1.0 (every core busy), over the next ``interval`` seconds.

    Like the CPU graph in Activity Monitor, all cores together.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    before = _cpu_ticks()
    time.sleep(interval)
    after = _cpu_ticks()
    # Each counter is 32-bit and wraps around: take each one's own difference, modulo 2**32.
    user, system_, idle, nice = ((later - earlier) % 2**32 for earlier, later in zip(before, after))
    total = user + system_ + idle + nice
    return min(1.0, (user + system_ + nice) / total) if total else 0.0


@dataclass(frozen=True)
class MemoryUsage:
    """The memory in use, in bytes, counted as Activity Monitor's Memory tab does."""

    total: int
    used: int
    """App memory, wired and compressed memory: what isn't free to give to an app."""
    wired: int
    """Memory the system keeps, which can't be compressed or paged out."""
    compressed: int
    cached: int
    """Recently used files, kept in memory while nothing needs it."""

    @property
    def free(self) -> int:
        return max(0, self.total - self.used)

    @property
    def percent(self) -> float:
        """``used`` as a fraction of ``total``, from 0.0 to 1.0."""
        return self.used / self.total if self.total else 0.0


def memory_usage() -> MemoryUsage:
    """How the memory is used right now: see :class:`MemoryUsage`."""
    require_macos()
    stats = _VMStatistics()
    count = ctypes.c_uint32(ctypes.sizeof(_VMStatistics) // 4)  # in 32-bit words
    mach = _libc.lib()
    if mach.host_statistics64(mach.mach_host_self(), _VM_INFO64, ctypes.byref(stats), ctypes.byref(count)) != 0:
        raise MacOSError("could not read the memory statistics")
    page = int.from_bytes(_sysctl("hw.pagesize"), "little") or 4096
    app = max(0, stats.internal_page_count - stats.purgeable_count)
    wired, compressed = stats.wire_count, stats.compressor_page_count
    return MemoryUsage(
        total=memory(),
        used=(app + wired + compressed) * page,
        wired=wired * page,
        compressed=compressed * page,
        cached=(stats.external_page_count + stats.purgeable_count) * page,
    )


def wait_for_idle(seconds: Union[float, timedelta], *, timeout: Optional[float] = None) -> bool:
    """
    Wait until nobody has touched the keyboard, mouse or trackpad for ``seconds``; return ``False`` on ``timeout``.

    For work that should wait for you to step away::

        macos.system.wait_for_idle(300)       # 5 minutes away
        run_backup()

    ``seconds`` may be a :class:`~datetime.timedelta`. See :func:`idle_time`.
    """
    wanted = seconds.total_seconds() if isinstance(seconds, timedelta) else float(seconds)
    if wanted < 0:
        raise ValueError("seconds must not be negative, not {}".format(seconds))
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        idle = idle_time().total_seconds()
        if idle >= wanted:
            return True
        # Nothing can happen sooner than the idle time reaching the goal: sleep until then.
        pause = max(0.2, wanted - idle)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            pause = min(pause, remaining)
        time.sleep(pause)


_IDLE_SLACK = 0.05  # seconds: the idle time and the clock aren't read at the very same instant


def wait_for_activity(*, timeout: Optional[float] = None, interval: float = 0.2) -> bool:
    """
    Wait until someone uses the keyboard, mouse or trackpad; return ``False`` on ``timeout``.

    ::

        macos.system.wait_for_idle(300)
        macos.system.wait_for_activity()      # back at the Mac
        macos.say("Welcome back")

    Checks every ``interval`` seconds.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    deadline = None if timeout is None else time.monotonic() + timeout
    start, idle_at_start = time.monotonic(), idle_time().total_seconds()
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return False
        time.sleep(interval if remaining is None else min(interval, remaining))
        # Without input, the idle time grows as fast as the clock; any input starts it over,
        # so it falls behind, even when the input came right after the previous reading.
        expected = idle_at_start + (time.monotonic() - start)
        if idle_time().total_seconds() < expected - _IDLE_SLACK:
            return True


@dataclass(frozen=True)
class Volume:
    """A mounted volume: the startup disk, an external drive, a disk image..."""

    name: str
    path: Path
    """Where it's mounted, e.g. ``/Volumes/Backup`` (``/`` for the startup disk)."""
    total: int
    """Capacity, in bytes."""
    free: int
    """Space available, in bytes, as Finder shows it (purgeable space included)."""
    is_internal: bool
    is_removable: bool
    """A USB stick, SD card or other removable media."""
    is_ejectable: bool
    """Whether :func:`eject` (or Finder's eject button) can unmount it."""


_SKIP_HIDDEN_VOLUMES = 1 << 1  # NSVolumeEnumerationSkipHiddenVolumes


def _resource(url: int, key: str) -> Optional[int]:
    """The value of an ``NSURL`` resource key (a Foundation constant), or ``None``."""
    constant = ctypes.c_void_p.in_dll(framework("Foundation"), key).value
    value = ctypes.c_void_p()
    ok = _objc.send(
        url,
        "getResourceValue:forKey:error:",
        ctypes.byref(value),
        constant,
        None,
        argtypes=(ctypes.c_void_p, _objc.id, ctypes.c_void_p),
        restype=_objc.BOOL,
    )
    return value.value if ok and value.value else None


def _number(url: int, key: str) -> int:
    value = _resource(url, key)
    return int(_objc.send(value, "longLongValue", restype=ctypes.c_longlong)) if value else 0


def _flag(url: int, key: str) -> bool:
    value = _resource(url, key)
    return bool(value) and bool(_objc.send(value, "boolValue", restype=_objc.BOOL))


def volumes() -> List[Volume]:
    """Return the mounted volumes that Finder shows, the startup disk first."""
    framework("Foundation")
    found = []
    with _objc.autorelease_pool():
        manager = _objc.send(_objc.cls("NSFileManager"), "defaultManager")
        urls = _objc.send(
            manager,
            "mountedVolumeURLsIncludingResourceValuesForKeys:options:",
            None,
            _SKIP_HIDDEN_VOLUMES,
            argtypes=(_objc.id, _objc.NSUInteger),
        )
        for url in _objc.nsarray(urls):
            path = _objc.pystring(_objc.send(url, "path"))
            if not path:
                continue
            name_ref = _resource(url, "NSURLVolumeLocalizedNameKey")
            free = _number(url, "NSURLVolumeAvailableCapacityForImportantUsageKey") or _number(
                url, "NSURLVolumeAvailableCapacityKey"
            )
            found.append(
                Volume(
                    name=_objc.pystring(name_ref) or os.path.basename(path) or path,
                    path=Path(path),
                    total=_number(url, "NSURLVolumeTotalCapacityKey"),
                    free=free,
                    is_internal=_flag(url, "NSURLVolumeIsInternalKey"),
                    is_removable=_flag(url, "NSURLVolumeIsRemovableKey"),
                    is_ejectable=_flag(url, "NSURLVolumeIsEjectableKey"),
                )
            )
    return sorted(found, key=lambda volume: volume.path != Path("/"))


# Just after a volume mounts, a system service (Spotlight indexing it, for one)
# can hold it for a moment, and ejecting it then fails with "busy". A program
# that keeps a file open on it holds it for good: once this wait is over, the
# last error is raised as is.
_BUSY_WAIT = 5.0
_BUSY_MARKERS = ("failed to eject", "failed to unmount", "could not be unmounted", "dissented", "resource busy")


def _release(args: List[str]) -> None:
    """Run an eject/detach command, retrying for a few seconds while the volume is busy."""
    deadline = time.monotonic() + _BUSY_WAIT
    while True:
        try:
            _run(args, timeout=_HDIUTIL_TIMEOUT)  # a disk that stopped answering mustn't hang the script
            return
        except CommandError as error:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not any(marker in error.stderr.lower() for marker in _BUSY_MARKERS):
                raise
            # Never sleep past the deadline, so the last try starts by then.
            time.sleep(min(0.5, remaining))


def eject(volume: Union[str, "os.PathLike[str]", Volume]) -> None:
    """
    Eject a volume, like Finder's eject button. Unsaved work on it is not waited for.

    ``volume`` is a :class:`Volume`, its name (``"Backup"``) or its mount
    path. When several volumes share a name, pass the path.

    A volume that's busy is retried for a few seconds, since macOS can hold one
    briefly right after it mounts. One that doesn't answer for a minute raises
    :class:`~macos.errors.CommandTimeoutError`. If it stays busy, the
    :class:`~macos.errors.CommandError` carries ``diskutil``'s message, which
    often names the process that refused; :func:`who_uses` lists this user's
    processes using it (system services don't show up there).
    """
    if isinstance(volume, Volume):
        chosen = volume
    else:
        text = os.fspath(volume)
        as_path = Path(text).expanduser()
        mounted = volumes()
        # Only the volumes Finder shows can be ejected: that leaves out the
        # startup disk's hidden system volumes (/System/Volumes/Data...).
        by_path = [found for found in mounted if found.path == as_path]
        by_name = [found for found in mounted if found.name == text]
        if not by_path and len(by_name) > 1:
            paths = ", ".join(str(found.path) for found in by_name)
            raise ValueError("more than one volume is named {!r} ({}); pass its path instead".format(text, paths))
        matches = by_path or by_name
        if not matches:
            raise ValueError("no mounted volume is named {!r}".format(text))
        chosen = matches[0]
    if chosen.path == Path("/"):
        raise ValueError("the startup disk can't be ejected")
    if not chosen.is_ejectable:
        raise ValueError("{} can't be ejected".format(chosen.name))
    _release(["diskutil", "eject", str(chosen.path)])


def _detach(devices: List[str]) -> bool:
    """Detach the whole disk of an image just attached (the shortest of its devices); whether there was one."""
    for device in sorted(devices, key=len)[:1]:
        try:
            _run(["hdiutil", "detach", device, "-force"], timeout=_HDIUTIL_TIMEOUT)
        except MacOSError:
            pass  # the error that made us detach is the one to raise
        return True
    return False


_HDIUTIL_TIMEOUT = 60.0  # seconds for a detach
_DEVICE = re.compile(r"/dev/disk\d+(?:s\d+)*")


def mount_image(path: Union[str, "os.PathLike[str]"], *, timeout: float = 300.0) -> Path:
    """
    Mount a disk image (``.dmg``, ``.iso``...) like double-clicking it, without opening a Finder window; return where.

    ::

        mounted = macos.system.mount_image("~/Downloads/Tool.dmg")   # PosixPath('/Volumes/Tool')
        ...
        macos.system.unmount_image(mounted)

    A license the image shows first is accepted. ``hdiutil`` checks a large
    image before mounting it, which takes a while: past ``timeout`` seconds it
    is stopped and :class:`~macos.errors.CommandTimeoutError` raised. When
    ``hdiutil``'s answer can't be read, the image is detached again and
    :class:`~macos.errors.MacOSError` raised with that answer. See also
    :func:`macos.apps.install_from_dmg`.
    """
    import plistlib
    from xml.parsers.expat import ExpatError

    image = Path(path).expanduser().resolve()
    if not image.is_file():
        raise FileNotFoundError(str(image))
    # "Y" answers the license agreement some images show before mounting. -quiet would hide the
    # -plist answer too (it closes the output): the license's text before the plist is skipped instead.
    output = _run(["hdiutil", "attach", "-nobrowse", "-noautoopen", "-plist", str(image)], input="Y\n", timeout=timeout)
    start = output.find("<?xml")
    details: Any = None
    try:
        details = plistlib.loads(output[start:].encode()) if start >= 0 else None
    except (plistlib.InvalidFileException, ValueError, ExpatError):  # cut short, or not a plist at all
        pass
    entities = details.get("system-entities") if isinstance(details, dict) else None
    if not isinstance(entities, list):
        # Attached, maybe, but where is unknown: detach the disk its text names, rather than leave it attached.
        detached = _detach(_DEVICE.findall(output))
        raise MacOSError(
            "hdiutil attached {} but its answer can't be read{}: {!r}".format(
                image, " (it was detached)" if detached else "", output[:500]
            )
        )
    entities = [entity for entity in entities if isinstance(entity, dict)]
    points = [str(entity["mount-point"]) for entity in entities if entity.get("mount-point")]
    if not points:
        # Attached without a volume: detach its disk, so the image isn't left attached.
        _detach([str(entity["dev-entry"]) for entity in entities if entity.get("dev-entry")])
        raise MacOSError("{} has no volume to mount".format(image))
    return Path(points[0])


def unmount_image(mount_point: Union[str, "os.PathLike[str]"], *, force: bool = False) -> None:
    """
    Unmount a disk image mounted with :func:`mount_image` (or from Finder), given where it's mounted.

    Like :func:`eject`, a busy image is retried for a few seconds, and one that
    doesn't answer for a minute raises :class:`~macos.errors.CommandTimeoutError`. ``force=True``
    unmounts it even while a program has files open on it.
    """
    _release(["hdiutil", "detach", str(Path(mount_point)), *(["-force"] if force else [])])


@dataclass(frozen=True)
class Update:
    """A software update macOS offers, as System Settings › General › Software Update lists it."""

    label: str
    """The name ``softwareupdate --install`` takes, such as ``'macOS Sequoia 15.8.1-24H32'``."""
    title: str
    version: str
    size: Optional[int]
    """In bytes."""
    recommended: bool
    restart: bool
    """Whether installing it restarts the Mac."""


# The fields of an update's second line, "Title: Safari, Version: 27.0, Size: 238423KiB, ...". Only these
# names start a field: a title with a comma ("Pro Video Formats, 2.3") stays whole.
_UPDATE_FIELD = re.compile(r"(?:^|,)\s*(Title|Version|Size|Recommended|Action|Build):\s*")


def _update_fields(details: str) -> Dict[str, str]:
    starts = list(_UPDATE_FIELD.finditer(details))
    fields = {}
    for match, following in zip(starts, starts[1:] + [None]):
        value = details[match.end():following.start() if following else len(details)]
        fields[match.group(1)] = value.strip().rstrip(",").strip()
    return fields


def _updates(output: str) -> List[Update]:
    found = []
    for label, details in re.findall(r"^\*\s*Label:\s*(.+?)\s*\n\s*(.+)$", output, re.M):
        fields = _update_fields(details)
        size = re.match(r"(\d+)\s*KiB", fields.get("Size", ""))
        found.append(
            Update(
                label=label,
                title=fields.get("Title", label).replace("\xa0", " "),
                version=fields.get("Version", ""),
                size=int(size.group(1)) * 1024 if size else None,
                recommended=fields.get("Recommended", "").upper() == "YES",
                restart=fields.get("Action", "").lower() == "restart",
            )
        )
    return found


def available_updates(*, timeout: float = 300.0) -> List[Update]:
    """
    The macOS and app updates Software Update offers; ``[]`` when everything is up to date.

    Asks Apple's servers, so it takes a while (often 10 to 30 seconds); past
    ``timeout`` seconds (a server that doesn't answer), it gives up with
    :class:`~macos.errors.CommandTimeoutError`. To install one, run
    ``softwareupdate --install "<label>"`` (with ``sudo`` for most).
    """
    return _updates(_run(["softwareupdate", "--list"], timeout=timeout))


def fonts() -> List[str]:
    """
    Return the font families installed on the Mac, sorted: ``['Arial', 'Avenir', ...]``.

    The names are the ones apps show in their font menus, including fonts the
    user installed. Handy to check a font exists before using it in a plot or
    an image.
    """
    framework("AppKit")
    with _objc.autorelease_pool():
        manager = _objc.send(_objc.cls("NSFontManager"), "sharedFontManager")
        families = _objc.nsarray(_objc.send(manager, "availableFontFamilies"))
        names = [_objc.pystring(family) or "" for family in families]
    # Hidden system families (".SF NS", ".Apple Color Emoji UI"...) can't be picked by name.
    return sorted((name for name in names if name and not name.startswith(".")), key=str.casefold)


_THERMAL_STATES = ("nominal", "fair", "serious", "critical")


def thermal_state() -> str:
    """
    How hot the Mac is running: ``'nominal'``, ``'fair'``, ``'serious'`` or ``'critical'``.

    ``'unknown'`` if a later macOS reports a state this package doesn't know.

    At ``'serious'`` macOS slows the processor down to cool it; at
    ``'critical'`` it's close to shutting down. A long job can check it and
    pause::

        while macos.system.thermal_state() in ("serious", "critical"):
            time.sleep(60)
    """
    framework("Foundation")
    with _objc.autorelease_pool():
        info = _objc.send(_objc.cls("NSProcessInfo"), "processInfo")
        state = int(_objc.send(info, "thermalState", restype=_objc.NSInteger))
    return _THERMAL_STATES[state] if 0 <= state < len(_THERMAL_STATES) else "unknown"


def lid_closed() -> bool:
    """
    Whether the MacBook's lid is closed, as when it runs with an external display (clamshell mode).

    Raises :class:`~macos.errors.NotSupportedError` on a Mac without a lid.
    """
    io = _iokit.lib()
    service = io.IOServiceGetMatchingService(0, io.IOServiceMatching(b"IOPMrootDomain"))
    if not service:
        raise MacOSError("the IOPMrootDomain service is not available")
    try:
        with _cf.owned(_cf.string("AppleClamshellState")) as key:
            with _cf.owned(io.IORegistryEntryCreateCFProperty(service, key, None, 0)) as value:
                if not value:
                    raise NotSupportedError("this Mac has no lid")
                return _cf.to_bool(value)
    finally:
        io.IOObjectRelease(service)


class _PropertyAddress(ctypes.Structure):
    # The same layout for CoreAudio and CoreMediaIO properties.
    _fields_ = [("selector", ctypes.c_uint32), ("scope", ctypes.c_uint32), ("element", ctypes.c_uint32)]


def _four_cc(text: str) -> int:
    return int.from_bytes(text.encode("ascii"), "big")


@lru_cache(maxsize=None)
def _media_io() -> ctypes.CDLL:
    media = framework("CoreMediaIO")
    address = ctypes.POINTER(_PropertyAddress)
    size = ctypes.POINTER(ctypes.c_uint32)
    media.CMIOObjectGetPropertyDataSize.argtypes = (ctypes.c_uint32, address, ctypes.c_uint32, ctypes.c_void_p, size)
    media.CMIOObjectGetPropertyDataSize.restype = ctypes.c_int32
    media.CMIOObjectGetPropertyData.argtypes = (
        ctypes.c_uint32,
        address,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        size,
        ctypes.c_void_p,
    )
    media.CMIOObjectGetPropertyData.restype = ctypes.c_int32
    return media


def _camera_property(target: int, selector: str) -> Optional[bytes]:
    media = _media_io()
    address = _PropertyAddress(_four_cc(selector), _four_cc("glob"), 0)
    size = ctypes.c_uint32()
    if media.CMIOObjectGetPropertyDataSize(target, ctypes.byref(address), 0, None, ctypes.byref(size)) != 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    used = ctypes.c_uint32()
    status = media.CMIOObjectGetPropertyData(
        target, ctypes.byref(address), 0, None, size.value, ctypes.byref(used), buffer
    )
    return buffer.raw[: used.value] if status == 0 else None


def _uints(raw: Optional[bytes]) -> List[int]:
    raw = raw or b""
    return [int.from_bytes(raw[index : index + 4], "little") for index in range(0, len(raw) - 3, 4)]


def camera_in_use() -> bool:
    """
    Whether an app is using a camera right now, as when its green light is on.

    Handy for an "on air" light, or to pause something noisy during video
    calls. It doesn't say which app. Needs no permission.
    """
    cameras = _uints(_camera_property(1, "dev#"))  # 1: kCMIOObjectSystemObject
    return any(_uints(_camera_property(camera, "gone"))[:1] == [1] for camera in cameras)


def microphone_in_use() -> bool:
    """
    Whether an app is recording from a microphone right now, as when the orange dot shows in the menu bar.

    It doesn't say which app. Needs no permission.
    """
    from . import audio

    processes = _uints(audio._property(audio._SYSTEM, "prs#"))
    if processes:
        # macOS 14+: each process says whether it records (kAudioProcessPropertyIsRunningInput).
        return any(audio._uint(process, "piri") for process in processes)
    # Before: whether an input device is running for any app. A headset
    # that only plays sound can count too.
    return any(audio._uint(device.id, "gone") for device in audio.inputs())


_DESKTOP_SERVICES = "com.apple.desktopservices"


def ds_store_on_network() -> bool:
    """Whether Finder writes ``.DS_Store`` files into network shares it opens."""
    return not defaults.read(_DESKTOP_SERVICES, "DSDontWriteNetworkStores", default=False)


def set_ds_store_on_network(on: bool = True) -> None:
    """
    Let Finder write ``.DS_Store`` files into network shares, or not (``False``), sparing everyone else on them.

    Takes effect at the next login.
    """
    defaults.write(_DESKTOP_SERVICES, "DSDontWriteNetworkStores", not on)


def ds_store_on_usb() -> bool:
    """Whether Finder writes ``.DS_Store`` files onto USB drives and other external disks."""
    return not defaults.read(_DESKTOP_SERVICES, "DSDontWriteUSBStores", default=False)


def set_ds_store_on_usb(on: bool = True) -> None:
    """Let Finder write ``.DS_Store`` files onto USB drives and external disks, or not. Takes effect at the next login."""
    defaults.write(_DESKTOP_SERVICES, "DSDontWriteUSBStores", not on)


def keep_windows_on_quit() -> bool:
    """Whether apps reopen the windows they had when they quit (unchecks "Close windows when quitting an app")."""
    return bool(defaults.read(defaults.GLOBAL, "NSQuitAlwaysKeepsWindows", default=False))


def set_keep_windows_on_quit(on: bool = True) -> None:
    """Make apps reopen their windows when opened again, or start fresh (``False``)."""
    defaults.write(defaults.GLOBAL, "NSQuitAlwaysKeepsWindows", bool(on))


def _restart_control_center() -> None:
    """Quit Control Center, which draws the menu bar's clock and icons: macOS starts it again, reading the settings."""
    try:
        _run(["killall", "ControlCenter"])
    except MacOSError:
        pass  # not running: it reads them when it starts


def battery_percentage_shown() -> bool:
    """Whether the battery icon in the menu bar shows the percentage."""
    return bool(defaults.read("com.apple.controlcenter", "BatteryShowPercentage", default=False, current_host=True))


def set_show_battery_percentage(on: bool = True) -> None:
    """Show the battery percentage next to its icon in the menu bar, or not."""
    defaults.write("com.apple.controlcenter", "BatteryShowPercentage", bool(on), current_host=True)
    _restart_control_center()


def save_to_icloud_by_default() -> bool:
    """Whether new documents are saved to iCloud Drive unless another place is chosen."""
    return bool(defaults.read(defaults.GLOBAL, "NSDocumentSaveNewDocumentsToCloud", default=True))


def set_save_to_icloud_by_default(on: bool = True) -> None:
    """Offer iCloud Drive first when saving a new document, or the Mac (``False``). Apps pick it up when reopened."""
    defaults.write(defaults.GLOBAL, "NSDocumentSaveNewDocumentsToCloud", bool(on))


def expanded_save_dialog() -> bool:
    """Whether the Save dialog opens expanded, with the sidebar and the folders."""
    return bool(defaults.read(defaults.GLOBAL, "NSNavPanelExpandedStateForSaveMode", default=False))


def set_expanded_save_dialog(on: bool = True) -> None:
    """Open the Save dialog expanded, with every folder, or small (``False``). Apps pick it up when reopened."""
    for key in ("NSNavPanelExpandedStateForSaveMode", "NSNavPanelExpandedStateForSaveMode2"):
        defaults.write(defaults.GLOBAL, key, bool(on))


_CLOCK = "com.apple.menuextra.clock"
# Name: (key, default).
_CLOCK_OPTIONS = {
    "seconds": ("ShowSeconds", False),
    "day_of_week": ("ShowDayOfWeek", True),
    "am_pm": ("ShowAMPM", True),
    "analog": ("IsAnalog", False),
}
_CLOCK_DATES = ("auto", "always", "never")  # ShowDate's 0, 1 and 2


def clock_format() -> Dict[str, object]:
    """
    How the menu bar's clock shows the time.

    ``{"seconds": False, "day_of_week": True, "am_pm": True, "analog": False, "date": "auto"}``;
    ``date`` is ``"auto"`` (when there's room), ``"always"`` or ``"never"``.
    """
    found: Dict[str, object] = {
        name: bool(defaults.read(_CLOCK, key, default=default)) for name, (key, default) in _CLOCK_OPTIONS.items()
    }
    date = int(defaults.read(_CLOCK, "ShowDate", default=0))
    found["date"] = _CLOCK_DATES[date] if 0 <= date < len(_CLOCK_DATES) else "auto"
    return found


def set_clock_format(
    *,
    seconds: Optional[bool] = None,
    day_of_week: Optional[bool] = None,
    am_pm: Optional[bool] = None,
    analog: Optional[bool] = None,
    date: Optional[str] = None,
) -> None:
    """
    Change how the menu bar's clock shows the time; the options left out stay as they are.

    ::

        macos.system.set_clock_format(seconds=True, date="always")

    ``date`` is ``"auto"`` (when there's room), ``"always"`` or ``"never"``.
    Whether it's 12 or 24 hours follows System Settings › General › Date & Time.
    """
    options = {"seconds": seconds, "day_of_week": day_of_week, "am_pm": am_pm, "analog": analog}
    if date is None and all(value is None for value in options.values()):
        raise ValueError("say what to change: seconds=, day_of_week=, am_pm=, analog= or date=")
    if date is not None and date not in _CLOCK_DATES:
        raise ValueError("date must be 'auto', 'always' or 'never', not {!r}".format(date))
    for name, value in options.items():
        if value is not None:
            defaults.write(_CLOCK, _CLOCK_OPTIONS[name][0], bool(value))
    if date is not None:
        defaults.write(_CLOCK, "ShowDate", _CLOCK_DATES.index(date))
    _restart_control_center()


# --- Region -----------------------------------------------------------------


def _locale_measurement() -> str:
    """The measurement system the region implies, when none was chosen."""
    framework("Foundation")
    with _objc.autorelease_pool():
        locale = _objc.send(_objc.cls("NSLocale"), "currentLocale")
        return "metric" if _objc.send(locale, "usesMetricSystem", restype=_objc.BOOL) else "us"


def measurement_units() -> str:
    """The units of measure: ``'metric'`` or ``'us'`` (inches, pounds, miles)."""
    metric = defaults.read(defaults.GLOBAL, "AppleMetricUnits")
    if metric is None:
        return _locale_measurement()
    return "metric" if metric else "us"


def set_measurement_units(units: str) -> None:
    """Use ``"metric"`` or ``"us"`` units, like System Settings › General › Language & Region. Apps pick it up when reopened."""
    if units not in ("metric", "us"):
        raise ValueError("units must be 'metric' or 'us', not {!r}".format(units))
    # macOS keeps both, and they must agree.
    defaults.write(defaults.GLOBAL, "AppleMetricUnits", units == "metric")
    defaults.write(defaults.GLOBAL, "AppleMeasurementUnits", "Centimeters" if units == "metric" else "Inches")


def temperature_unit() -> str:
    """The unit of temperatures: ``'celsius'`` or ``'fahrenheit'``."""
    found = defaults.read(defaults.GLOBAL, "AppleTemperatureUnit")
    if found in ("Celsius", "Fahrenheit"):
        return found.lower()
    return "fahrenheit" if measurement_units() == "us" else "celsius"


def set_temperature_unit(unit: str) -> None:
    """Show temperatures in ``"celsius"`` or ``"fahrenheit"``, in Weather and everywhere. Apps pick it up when reopened."""
    if unit not in ("celsius", "fahrenheit"):
        raise ValueError("unit must be 'celsius' or 'fahrenheit', not {!r}".format(unit))
    defaults.write(defaults.GLOBAL, "AppleTemperatureUnit", unit.capitalize())


# --- Photos and devices ---------------------------------------------------------


def open_photos_on_device_connect() -> bool:
    """Whether Photos opens by itself when an iPhone, an iPad or a camera is connected."""
    return not defaults.read("com.apple.ImageCapture", "disableHotPlug", default=False, current_host=True)


def set_open_photos_on_device_connect(on: bool = True) -> None:
    """Let Photos open by itself when an iPhone, an iPad or a camera is connected, or not (``False``)."""
    defaults.write("com.apple.ImageCapture", "disableHotPlug", not on, current_host=True)


# --- The menu bar ---------------------------------------------------------------


def menu_bar_spacing() -> Optional[int]:
    """The space around each icon on the right of the menu bar, in points; ``None`` for macOS's own."""
    found = defaults.read(defaults.GLOBAL, "NSStatusItemSpacing", current_host=True)
    return None if found is None else int(found)


def set_menu_bar_spacing(spacing: Optional[int], *, padding: Optional[int] = None) -> None:
    """
    Space the icons on the right of the menu bar ``spacing`` points apart, or as macOS does (``None``).

    ::

        macos.system.set_menu_bar_spacing(6)   # more icons fit beside the notch

    ``padding`` is the room around an icon when clicked (``spacing`` by
    default). macOS's own is about 16 and 12; 0 to 30 is allowed. Takes
    effect at the next login.
    """
    if spacing is None:
        for key in ("NSStatusItemSpacing", "NSStatusItemSelectionPadding"):
            defaults.delete(defaults.GLOBAL, key, current_host=True)
        return
    padding = spacing if padding is None else padding
    for name, value in (("spacing", spacing), ("padding", padding)):
        if not 0 <= value <= 30:
            raise ValueError("{} must be from 0 to 30 points, not {}".format(name, value))
    defaults.write(defaults.GLOBAL, "NSStatusItemSpacing", int(spacing), current_host=True)
    defaults.write(defaults.GLOBAL, "NSStatusItemSelectionPadding", int(padding), current_host=True)


# The menu bar's items from Control Center, as it names them.
_MENU_BAR_ITEMS = {
    "wifi": "WiFi",
    "bluetooth": "Bluetooth",
    "sound": "Sound",
    "display": "Display",
    "battery": "Battery",
    "focus": "FocusModes",
    "now_playing": "NowPlaying",
    "screen_mirroring": "ScreenMirroring",
    "stage_manager": "StageManager",
    "keyboard_brightness": "KeyboardBrightness",
}
_SHOWN, _HIDDEN = 18, 8  # Control Center's "always show in the menu bar", and "don't show"
MENU_BAR_ITEMS = tuple(_MENU_BAR_ITEMS)
"""The menu bar's icons :func:`set_menu_bar_items` shows and hides."""


def menu_bar_items() -> Dict[str, bool]:
    """Which of Control Center's icons the menu bar shows: ``{"wifi": True, "bluetooth": False, ...}``."""
    return {
        name: bool(defaults.read("com.apple.controlcenter", "NSStatusItem Visible " + item, default=False))
        for name, item in _MENU_BAR_ITEMS.items()
    }


def set_menu_bar_items(**items: bool) -> None:
    """
    Show or hide Control Center's icons in the menu bar, like System Settings › Control Center.

    ::

        macos.system.set_menu_bar_items(bluetooth=True, now_playing=False)

    Each name is one of :data:`MENU_BAR_ITEMS`; those left out stay as
    they are. The icons stay in Control Center either way. Applies at once.
    """
    if not items:
        raise ValueError("say which icons to show or hide, such as bluetooth=True")
    unknown = set(items) - set(_MENU_BAR_ITEMS)
    if unknown:
        raise ValueError("unknown menu bar items: {}; use {}".format(", ".join(sorted(unknown)), ", ".join(MENU_BAR_ITEMS)))
    for name, on in items.items():
        item = _MENU_BAR_ITEMS[name]
        # Control Center keeps the choice for this Mac, and only draws the icons it's also told are visible.
        defaults.write("com.apple.controlcenter", item, _SHOWN if on else _HIDDEN, current_host=True)
        defaults.write("com.apple.controlcenter", "NSStatusItem Visible " + item, bool(on))
    _restart_control_center()


# --- Security -----------------------------------------------------------------


@dataclass(frozen=True)
class SecurityStatus:
    """Whether the Mac's protections are on; ``None`` when macOS didn't say."""

    filevault: Optional[bool]
    """The disk is encrypted."""
    firewall: Optional[bool]
    """The application firewall blocks unwanted incoming connections."""
    gatekeeper: Optional[bool]
    """Apps are checked before they open."""
    sip: Optional[bool]
    """System Integrity Protection guards the system's files."""


def _state(args: List[str], on: str, off: str) -> Optional[bool]:
    try:
        output = _run(args).lower()
    except (MacOSError, OSError):
        return None
    if on in output:
        return True
    if off in output:
        return False
    return None


def security_status() -> SecurityStatus:
    """
    Whether FileVault, the firewall, Gatekeeper and System Integrity Protection are on, without an administrator's password.

    ::

        status = macos.system.security_status()
        if status.filevault is False:   # None: macOS didn't say
            print("The disk isn't encrypted")

    Handy to check a fleet of Macs against a security policy.
    """
    require_macos()
    firewall: Optional[bool] = None
    try:
        found = re.search(r"State = (\d)", _run(["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"]))
        firewall = None if found is None else found.group(1) != "0"
    except (MacOSError, OSError):
        pass
    return SecurityStatus(
        filevault=_state(["fdesetup", "status"], "filevault is on", "filevault is off"),
        firewall=firewall,
        gatekeeper=_state(["spctl", "--status"], "assessments enabled", "assessments disabled"),
        sip=_state(["csrutil", "status"], "status: enabled", "status: disabled"),
    )


# --- Processes ------------------------------------------------------------------

_PROC_PIDTBSDINFO, _PROC_PIDTASKINFO, _PROC_PIDT_SHORTBSDINFO = 3, 4, 13
_PATH_MAX = 4096


class _BSDInfo(ctypes.Structure):
    # <sys/proc_info.h>'s proc_bsdinfo.
    _fields_ = [
        ("flags", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("nice", ctypes.c_int32),
        ("start_tvsec", ctypes.c_uint64),
        ("start_tvusec", ctypes.c_uint64),
    ]


class _ShortInfo(ctypes.Structure):
    # <sys/proc_info.h>'s proc_bsdshortinfo: what any user may read of any process.
    _fields_ = [
        ("pid", ctypes.c_uint32),
        ("ppid", ctypes.c_uint32),
        ("pgid", ctypes.c_uint32),
        ("status", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16),
        ("flags", ctypes.c_uint32),
        ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32),
        ("ruid", ctypes.c_uint32),
        ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32),
        ("svgid", ctypes.c_uint32),
        ("rfu", ctypes.c_uint32),
    ]


class _TaskInfo(ctypes.Structure):
    # <sys/proc_info.h>'s proc_taskinfo.
    _fields_ = [
        ("virtual_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("total_user", ctypes.c_uint64),
        ("total_system", ctypes.c_uint64),
        ("threads_user", ctypes.c_uint64),
        ("threads_system", ctypes.c_uint64),
        ("policy", ctypes.c_int32),
        ("faults", ctypes.c_int32),
        ("pageins", ctypes.c_int32),
        ("cow_faults", ctypes.c_int32),
        ("messages_sent", ctypes.c_int32),
        ("messages_received", ctypes.c_int32),
        ("syscalls_mach", ctypes.c_int32),
        ("syscalls_unix", ctypes.c_int32),
        ("csw", ctypes.c_int32),
        ("threadnum", ctypes.c_int32),
        ("numrunning", ctypes.c_int32),
        ("priority", ctypes.c_int32),
    ]


def _libproc() -> Tuple[ctypes.CDLL, float]:
    """libproc (part of libSystem), and how many nanoseconds a tick of its CPU times lasts."""
    return _libc.lib(), _libc.tick()


@dataclass(frozen=True)
class Process:
    """A running process, as it was when read."""

    pid: int
    name: str
    path: Optional[Path]
    """Its executable; ``None`` for the few the system hides."""
    user: Optional[str]
    parent_pid: int
    started: Optional[datetime]
    """``None`` for other users' processes."""
    memory: Optional[int]
    """Memory it uses (resident), in bytes; ``None`` for other users' processes."""
    cpu_time: Optional[timedelta]
    """Processor time used since it started; ``None`` for other users' processes."""
    cpu_percent: Optional[float] = None
    """Share of a processor core it used lately, like Activity Monitor's % CPU (over 100 on several cores).
    Only with ``cpu=True``; ``None`` otherwise, and for other users' processes."""

    def kill(self, *, force: bool = False) -> None:
        """
        Ask the process to quit, or end it at once (``force=True``). See :func:`kill`.

        Raises :class:`ProcessLookupError` when it has quit, even if another process now has its pid.
        """
        kill(self, force=force)


def _user(uid: int) -> Optional[str]:
    import pwd

    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return None


def _process_name(name: bytes, short_name: bytes, path: Optional[Path]) -> str:
    """The process's name: the kernel cuts it to its fields' sizes, 31 characters or 15 for the short one."""
    raw, limit = (name, 31) if name else (short_name, 15)
    if path and len(raw) >= limit:
        return path.name  # cut: the executable's name is whole
    return raw.decode("utf-8", "replace")


def _info(lib: ctypes.CDLL, pid: int, flavor: int, into: ctypes.Structure) -> bool:
    return bool(lib.proc_pidinfo(pid, flavor, 0, ctypes.byref(into), ctypes.sizeof(into)) == ctypes.sizeof(into))


def _read_process(pid: int) -> Optional[Process]:
    lib, tick = _libproc()
    short = _ShortInfo()
    if not _info(lib, pid, _PROC_PIDT_SHORTBSDINFO, short):
        return None  # gone
    buffer = ctypes.create_string_buffer(_PATH_MAX)
    path = Path(buffer.value.decode("utf-8", "replace")) if lib.proc_pidpath(pid, buffer, _PATH_MAX) > 0 else None
    # The rest only for this user's processes: macOS keeps other users' to themselves.
    full, task = _BSDInfo(), _TaskInfo()
    has_full, has_task = _info(lib, pid, _PROC_PIDTBSDINFO, full), _info(lib, pid, _PROC_PIDTASKINFO, task)
    name = _process_name(full.name if has_full else b"", short.comm, path)
    return Process(
        pid=pid,
        name=name,
        path=path,
        user=_user(short.uid),
        parent_pid=short.ppid,
        started=datetime.fromtimestamp(full.start_tvsec + full.start_tvusec / 1e6) if has_full and full.start_tvsec else None,
        memory=int(task.resident_size) if has_task else None,
        cpu_time=timedelta(microseconds=(task.total_user + task.total_system) * tick / 1000) if has_task else None,
    )


_CPU_INTERVAL = 0.5  # seconds between the two readings that give the % CPU


def _with_cpu(found: List[Process], again: Callable[[], Dict[int, Process]], started: float) -> List[Process]:
    """``found`` with each process's % CPU, from how much processor time it used since ``started``."""
    import dataclasses

    time.sleep(max(0.0, started + _CPU_INTERVAL - time.monotonic()))
    later = again()
    elapsed = time.monotonic() - started
    measured = []
    for process in found:
        now = later.get(process.pid)
        if now is None or now.cpu_time is None or process.cpu_time is None or now.started != process.started:
            measured.append(process)  # gone, unreadable, or another process with the same pid
            continue
        used = (now.cpu_time - process.cpu_time).total_seconds()
        measured.append(dataclasses.replace(now, cpu_percent=round(max(used, 0.0) / elapsed * 100, 1)))
    return measured


def processes(*, cpu: bool = False) -> List[Process]:
    """
    The running processes, by pid, like Activity Monitor's list.

    ::

        biggest = sorted(macos.system.processes(), key=lambda p: p.memory or 0, reverse=True)[:5]
        [(p.name, p.memory // 2**20) for p in biggest]   # [('Safari', 1840), ('Code Helper', 950), ...]

        busiest = sorted(macos.system.processes(cpu=True), key=lambda p: p.cpu_percent or 0)[-1]
        busiest.name, busiest.cpu_percent                  # ('Xcode', 187.5)

    ``cpu=True`` also measures each process's :attr:`~Process.cpu_percent`,
    over half a second.

    Other users' processes, the system's included, come without their
    memory, processor time and start, which macOS keeps from this user; an
    administrator's script run with ``sudo`` sees them all. No permission
    is needed.
    """
    def read_all() -> List[Process]:
        found = [_read_process(pid) for pid in sorted(set(_pids()))]
        return [process for process in found if process is not None]

    require_macos()
    started = time.monotonic()
    found = read_all()
    if not cpu:
        return found
    return _with_cpu(found, lambda: {process.pid: process for process in read_all()}, started)


def process(pid: int, *, cpu: bool = False) -> Optional[Process]:
    """The process with ``pid``, or ``None`` when there's none (it may have quit). ``cpu`` works as for :func:`processes`."""
    if pid <= 0:
        raise ValueError("pid must be positive, not {}".format(pid))
    started = time.monotonic()
    found = _read_process(pid)
    if found is None or not cpu:
        return found

    def again() -> Dict[int, Process]:
        later = _read_process(pid)
        return {pid: later} if later else {}

    return _with_cpu([found], again, started)[0]


def _check_same(expected: Process) -> None:
    """
    Raise :class:`ProcessLookupError` unless ``expected``'s pid still belongs to that very process.

    macOS gives a quitted process's pid to a new one sooner or later: a :class:`Process` kept
    a while could otherwise end an unrelated program. Its start time tells them apart; its
    executable too, when both are known (other users' processes have no start time to read).
    """
    current = _read_process(expected.pid)
    if current is None:
        raise ProcessLookupError("{} (pid {}) has quit".format(expected.name, expected.pid))
    if expected.started is not None and current.started is not None and current.started != expected.started:
        changed = True
    elif expected.path is not None and current.path is not None and current.path != expected.path:
        changed = True
    else:
        changed = expected.started is not None and current.started is None  # was readable, now isn't: not the same
    if changed:
        raise ProcessLookupError(
            "{} (pid {}) has quit; pid {} is now {}'s".format(expected.name, expected.pid, expected.pid, current.name)
        )


def kill(process: Union[int, Process], *, force: bool = False) -> None:
    """
    Ask a process (a :class:`Process` or its pid) to quit, as ``kill`` does, or end it at once (``force=True``).

    Asking lets it save and clean up, and it may take a moment or refuse;
    ``force`` doesn't. To quit an app, prefer :meth:`macos.apps.App.quit`.
    A process already gone raises :class:`ProcessLookupError`; another
    user's, :class:`PermissionError`.

    Given a :class:`Process`, it first checks the pid still belongs to that
    process (by its start time and executable), and raises
    :class:`ProcessLookupError` if it quit and another took the pid. Given
    a bare pid, it signals whatever process has it now.
    """
    import signal

    require_macos()
    pid = process.pid if isinstance(process, Process) else int(process)
    if pid <= 1:
        raise ValueError("pid must be a process's, not {}".format(pid))
    if isinstance(process, Process):
        _check_same(process)  # as close to the signal as can be: the pid could still change in between, rarely
    os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


# --- Ports ------------------------------------------------------------------------

_PROC_PIDLISTFDS, _PROC_PIDFDSOCKETINFO, _PROX_FDTYPE_SOCKET = 1, 3, 2
# Offsets in <sys/proc_info.h>'s socket_fdinfo: a proc_fileinfo (24 bytes), then a socket_info.
_SOCKET = 24
_SOCKET_TYPE, _SOCKET_FAMILY, _SOCKET_KIND = _SOCKET + 152, _SOCKET + 160, _SOCKET + 232
_PROTO = _SOCKET + 240  # the in_sockinfo (or tcp_sockinfo, which starts with one)
_REMOTE_PORT, _LOCAL_PORT, _TCP_STATE = _PROTO, _PROTO + 4, _PROTO + 80
_REMOTE_ADDRESS, _LOCAL_ADDRESS = _PROTO + 32, _PROTO + 48
_SOCKINFO_IN, _SOCKINFO_TCP = 1, 2
_AF_INET, _AF_INET6 = 2, 30
_SOCK_STREAM, _SOCK_DGRAM = 1, 2
_SOCKET_INFO_SIZE = 1024  # more than socket_fdinfo needs, whatever its protocol's part


class _FDInfo(ctypes.Structure):
    _fields_ = [("fd", ctypes.c_int32), ("type", ctypes.c_uint32)]


_PROX_FDTYPE_VNODE = 1  # a file or a folder
_PROC_PIDFDVNODEPATHINFO, _PROC_PIDVNODEPATHINFO = 2, 9
_MAXPATHLEN = 1024
# A vnode_info_path is a vnode_info (152 bytes), then the path; a file descriptor's comes after a proc_fileinfo.
_VNODE_INFO = 152
_FILE_PATH = _SOCKET + _VNODE_INFO
_FILE_INFO_SIZE = _FILE_PATH + _MAXPATHLEN
_FOLDERS_INFO_SIZE = 2 * (_VNODE_INFO + _MAXPATHLEN)  # the working folder's, then the root's
_TCP_STATES = {
    0: "closed",
    1: "listen",
    2: "syn_sent",
    3: "syn_received",
    4: "established",
    5: "close_wait",
    6: "fin_wait_1",
    7: "closing",
    8: "last_ack",
    9: "fin_wait_2",
    10: "time_wait",
}


@dataclass(frozen=True)
class Port:
    """A port a process listens on: a TCP server, or a bound UDP socket."""

    port: int
    protocol: str
    """``'tcp'`` or ``'udp'``."""
    address: str
    """The address it listens on: ``'0.0.0.0'`` or ``'::'`` for every one, ``'127.0.0.1'`` for this Mac only..."""
    pid: int
    process: str
    """The process's name."""


@dataclass(frozen=True)
class Connection:
    """A network connection a process has open: its end, and the other one."""

    protocol: str
    """``'tcp'`` or ``'udp'``."""
    local_address: str
    local_port: int
    remote_address: str
    remote_port: int
    state: Optional[str]
    """TCP's state: ``'established'``, ``'syn_sent'``, ``'close_wait'``, ``'time_wait'``...; ``None`` for UDP."""
    pid: int
    process: str
    """The process's name."""


class _Socket(NamedTuple):
    protocol: str
    local_address: str
    local_port: int
    remote_address: str
    remote_port: int
    state: Optional[str]


def _descriptors(lib: ctypes.CDLL, pid: int, kind: int) -> List[int]:
    """The file descriptors of one kind that ``pid`` has open; ``[]`` when it can't be read (another user's)."""
    size = lib.proc_pidinfo(pid, _PROC_PIDLISTFDS, 0, None, 0)
    if size <= 0:
        return []
    # Files can open between the sizing call and the real one: leave room, and retry when it came back full.
    capacity = size // ctypes.sizeof(_FDInfo) + 16
    while True:
        entries = (_FDInfo * capacity)()
        size = lib.proc_pidinfo(pid, _PROC_PIDLISTFDS, 0, entries, ctypes.sizeof(entries))
        count = max(size, 0) // ctypes.sizeof(_FDInfo)
        if count < capacity:
            return [entry.fd for entry in entries[:count] if entry.type == kind]
        capacity *= 2


def _sockets(lib: ctypes.CDLL, pid: int) -> List[int]:
    return _descriptors(lib, pid, _PROX_FDTYPE_SOCKET)


def _address(raw: bytes, family: int) -> str:
    import socket

    if family == _AF_INET:
        return socket.inet_ntop(socket.AF_INET, raw[12:16])  # an IPv4 address sits at the end of the 16 bytes
    return socket.inet_ntop(socket.AF_INET6, raw)


def _socket(lib: ctypes.CDLL, pid: int, fd: int) -> Optional[_Socket]:
    """An internet socket's two ends, or ``None`` for any other kind (Unix sockets...)."""
    import socket

    info = ctypes.create_string_buffer(_SOCKET_INFO_SIZE)
    if lib.proc_pidfdinfo(pid, fd, _PROC_PIDFDSOCKETINFO, info, _SOCKET_INFO_SIZE) <= _TCP_STATE:
        return None

    def number(offset: int) -> int:
        return int(ctypes.c_int32.from_buffer(info, offset).value)

    family, kind, socket_type = number(_SOCKET_FAMILY), number(_SOCKET_KIND), number(_SOCKET_TYPE)
    if family not in (_AF_INET, _AF_INET6) or kind not in (_SOCKINFO_IN, _SOCKINFO_TCP):
        return None
    if socket_type == _SOCK_STREAM and kind == _SOCKINFO_TCP:
        protocol, state = "tcp", _TCP_STATES.get(number(_TCP_STATE))
    elif socket_type == _SOCK_DGRAM:
        protocol, state = "udp", None
    else:
        return None
    return _Socket(
        protocol=protocol,
        local_address=_address(info.raw[_LOCAL_ADDRESS:_LOCAL_ADDRESS + 16], family),
        local_port=socket.ntohs(number(_LOCAL_PORT) & 0xFFFF),
        remote_address=_address(info.raw[_REMOTE_ADDRESS:_REMOTE_ADDRESS + 16], family),
        remote_port=socket.ntohs(number(_REMOTE_PORT) & 0xFFFF),
        state=state,
    )


def _each_socket() -> Iterator[Tuple[int, str, _Socket]]:
    """``(pid, process name, socket)`` for every internet socket this user's processes have."""
    require_macos()
    lib, _ = _libproc()
    for pid in _pids():
        fds = _sockets(lib, pid)
        if not fds:
            continue
        process = _read_process(pid)
        name = process.name if process else str(pid)
        for fd in fds:
            found = _socket(lib, pid, fd)
            if found:
                yield pid, name, found


def ports() -> List[Port]:
    """
    The ports processes listen on: TCP servers and bound UDP sockets, by port.

    ::

        for port in macos.system.ports():
            print(port.port, port.protocol, port.process)   # 5432 tcp postgres, 8000 tcp Python, ...

    Like ``lsof -i`` without ``sudo``: other users' processes, the
    system's included, are left out, since macOS keeps them from this user.
    For the connections in progress, see :func:`connections`.
    """
    found = set()
    for pid, name, entry in _each_socket():
        listening = entry.state == "listen" if entry.protocol == "tcp" else not entry.remote_port  # UDP: not connected
        if listening and entry.local_port:
            found.add(Port(port=entry.local_port, protocol=entry.protocol, address=entry.local_address, pid=pid, process=name))
    return sorted(found, key=lambda port: (port.port, port.protocol, port.address, port.pid))


def port_owner(port: int, protocol: str = "tcp") -> Optional[Process]:
    """
    The process listening on ``port``, or ``None``: what's using port 8000?

    ::

        owner = macos.system.port_owner(8000)
        if owner:
            print(owner.name, owner.pid)   # Python 4123
            owner.kill()

    ``protocol`` is ``"tcp"`` (the default) or ``"udp"``. Only this user's
    processes are seen, as with :func:`ports`.
    """
    if not 0 < port < 65536:
        raise ValueError("port must be from 1 to 65535, not {}".format(port))
    if protocol not in ("tcp", "udp"):
        raise ValueError("protocol must be 'tcp' or 'udp', not {!r}".format(protocol))
    for found in ports():
        if found.port == port and found.protocol == protocol:
            return _read_process(found.pid)
    return None


def connections() -> List[Connection]:
    """
    The network connections processes have open: which address and port each is talking to.

    ::

        for connection in macos.system.connections():
            print(connection.process, connection.remote_address, connection.remote_port, connection.state)
            # Google Chrome 142.250.79.46 443 established

    TCP connections in any state but listening (servers are in :func:`ports`),
    and UDP sockets connected to an address. Like ``lsof -i`` without
    ``sudo``: only this user's processes are seen.
    """
    found = set()
    for pid, name, entry in _each_socket():
        if entry.remote_port and entry.state != "listen":
            found.add(Connection(**entry._asdict(), pid=pid, process=name))
    return sorted(found, key=lambda connection: (connection.process.lower(), connection.pid, connection.remote_address))


# --- Open files -------------------------------------------------------------------


class _Opened(NamedTuple):
    path: str
    file: Optional[Tuple[int, int]]
    """Its device and inode, which name it whatever the link it was opened by; ``None`` when unknown."""


def _vnode(raw: bytes, start: int) -> _Opened:
    """A vnode_info_path starting at ``start``: its vinfo_stat's device and inode, then its path."""
    device = int(ctypes.c_uint32.from_buffer_copy(raw, start).value)
    inode = int(ctypes.c_uint64.from_buffer_copy(raw, start + 8).value)
    name = raw[start + _VNODE_INFO:start + _VNODE_INFO + _MAXPATHLEN].split(b"\x00", 1)[0]
    return _Opened(os.fsdecode(name), (device, inode))  # fsdecode: any bytes a name holds survive


def _files(lib: ctypes.CDLL, pid: int) -> List[_Opened]:
    """What ``pid`` has open, its working folder and its executable; ``[]`` for another user's process."""
    opened = []
    for fd in _descriptors(lib, pid, _PROX_FDTYPE_VNODE):
        info = ctypes.create_string_buffer(_FILE_INFO_SIZE)
        if lib.proc_pidfdinfo(pid, fd, _PROC_PIDFDVNODEPATHINFO, info, _FILE_INFO_SIZE) > _FILE_PATH:
            opened.append(_vnode(info.raw, _SOCKET))  # after the proc_fileinfo
    folders = ctypes.create_string_buffer(_FOLDERS_INFO_SIZE)
    if lib.proc_pidinfo(pid, _PROC_PIDVNODEPATHINFO, 0, folders, _FOLDERS_INFO_SIZE) > _VNODE_INFO:
        opened.append(_vnode(folders.raw, 0))  # the working folder
    executable = ctypes.create_string_buffer(_PATH_MAX)
    if lib.proc_pidpath(pid, executable, _PATH_MAX) > 0 and opened:  # only for processes it can look into
        opened.append(_Opened(os.fsdecode(executable.value), None))
    return [entry for entry in opened if entry.path]


def open_files(process: Union[int, Process]) -> List[Path]:
    """
    The files and folders a process (a :class:`Process` or its pid) has open, with its working folder and executable.

    ``[]`` for another user's process, which macOS keeps from this user.
    """
    require_macos()
    pid = process.pid if isinstance(process, Process) else int(process)
    lib, _ = _libproc()
    return sorted({Path(entry.path) for entry in _files(lib, pid)})


def _is_in(path: str, target: str) -> bool:
    """Whether ``path`` is ``target`` or inside it."""
    folder = target.rstrip("/") or "/"
    return path.rstrip("/") == folder or path.startswith(folder if folder == "/" else folder + "/")


def who_uses(path: Union[str, "os.PathLike[str]"]) -> List[Process]:
    """
    The processes using ``path``: with it open, or a file in it, working in it, or run from it.

    ::

        macos.system.who_uses("/Volumes/Backup")   # [Process(name='Preview', ...)]: why the disk won't eject

    For a folder or a disk, anything inside counts; a file counts under any
    of its names (hard links). Like ``lsof`` without ``sudo``: only this
    user's processes are seen.
    """
    target = os.path.realpath(os.path.expanduser(os.fspath(path)))
    if not os.path.exists(target):
        raise FileNotFoundError(target)
    require_macos()
    lib, _ = _libproc()
    details = os.stat(target)
    same_file = None if os.path.isdir(target) else (details.st_dev & 0xFFFFFFFF, details.st_ino)

    def uses(entry: _Opened) -> bool:
        if same_file and entry.file == same_file:
            return True  # the same file, opened by another of its names
        return _is_in(os.path.realpath(entry.path), target)

    users = []
    for pid in _pids():
        if any(uses(entry) for entry in _files(lib, pid)):
            found = _read_process(pid)
            if found:
                users.append(found)
    return users


# --- Network use by process ----------------------------------------------------


@dataclass(frozen=True)
class NetworkUsage:
    """How much a process sent and received over the network."""

    pid: int
    process: str
    """The process's name."""
    received: int
    """In bytes: since it started, or in the interval asked for."""
    sent: int


def _nettop_samples(interval: Optional[float]) -> List[Tuple[int, str, int, int]]:
    """``(pid, name, received, sent)`` rows: the totals, or the deltas over ``interval`` seconds."""
    args = ["nettop", "-P", "-x", "-J", "bytes_in,bytes_out"]
    seconds = 0
    if interval is None:
        args += ["-L", "1"]
    else:
        seconds = max(1, round(interval))
        args += ["-L", "2", "-d", "-s", str(seconds)]
    # Its samples take a moment beyond the interval; a nettop that hangs past that is stopped.
    return _nettop_rows(_run(args, timeout=seconds + _NETTOP_SLACK))


_NETTOP_SLACK = 120.0  # seconds nettop may take beyond the interval it measures


def _nettop_rows(output: str) -> List[Tuple[int, str, int, int]]:
    """The rows of nettop's last sample: each sample starts with a header naming the columns."""
    lines = output.splitlines()
    headers = [index for index, line in enumerate(lines) if "bytes_in,bytes_out" in line]
    rows = []
    for line in lines[headers[-1] + 1:] if headers else []:  # the last sample: the deltas, with -d
        # Without a terminal, nettop adds the time as a first column: the last three are always ours.
        parts = line.strip().rstrip(",").split(",")
        if len(parts) < 3:
            continue
        name, _, pid = parts[-3].rpartition(".")
        if name and pid.isdigit() and parts[-2].isdigit() and parts[-1].isdigit():
            rows.append((int(pid), name, int(parts[-2]), int(parts[-1])))
    return rows


def network_usage(interval: Optional[float] = None) -> List[NetworkUsage]:
    """
    How much each process received and sent over the network, the busiest first: who's using the internet?

    ::

        for use in macos.system.network_usage(interval=2)[:5]:
            print(use.process, use.received, use.sent)   # bytes in those 2 seconds

    Without ``interval``, the totals since each process started; with it,
    what they moved in that many seconds (at least 1). Unlike the other
    process functions, it sees every user's processes, the system's
    included. Goes through ``nettop``; one that doesn't answer within 120
    seconds past ``interval`` raises :class:`~macos.errors.CommandTimeoutError`.
    """
    if interval is not None and interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    require_macos()
    found = []
    for pid, name, received, sent in _nettop_samples(interval):
        process = _read_process(pid)
        full = process.name if process and len(name) >= 15 else name  # nettop cuts names at 15 characters
        found.append(NetworkUsage(pid=pid, process=full, received=received, sent=sent))
    return sorted(found, key=lambda use: (use.received + use.sent, -use.pid), reverse=True)


# --- Energy use by process ------------------------------------------------------

_RUSAGE_INFO_V6 = 6
_RUSAGE_INFO_SIZE = 16 + 56 * 8  # rusage_info_v6: a 16-byte UUID, then 56 64-bit numbers
_ENERGY_NJ = 16 + 40 * 8  # ri_energy_nj: energy used since the process started, in nanojoules
_STARTED = 16 + 8 * 8  # ri_proc_start_abstime: when it started, which tells a new process with the same pid
_DISK_READ, _DISK_WRITTEN = 16 + 16 * 8, 16 + 17 * 8  # ri_diskio_bytesread, ri_diskio_byteswritten


@dataclass(frozen=True)
class EnergyUsage:
    """How much power a process drew, and how much it read and wrote on disk, over an interval."""

    pid: int
    process: str
    """The process's name."""
    watts: float
    """Average power it drew, in watts: what drains the battery."""
    disk_read: int
    """Bytes it read from disk in the interval."""
    disk_written: int
    """Bytes it wrote to disk in the interval."""


def _rusage(lib: ctypes.CDLL, pid: int) -> Optional[Tuple[int, int, int, int]]:
    """``(energy in nanojoules, bytes read, bytes written, start)`` since ``pid`` started; ``None`` when it can't be read."""
    info = ctypes.create_string_buffer(_RUSAGE_INFO_SIZE)
    if lib.proc_pid_rusage(pid, _RUSAGE_INFO_V6, ctypes.byref(info)) != 0:
        return None  # another user's, or gone

    def number(offset: int) -> int:
        return int(ctypes.c_uint64.from_buffer(info, offset).value)

    return number(_ENERGY_NJ), number(_DISK_READ), number(_DISK_WRITTEN), number(_STARTED)


def energy_usage(interval: float = 1.0) -> List[EnergyUsage]:
    """
    How much power each process drew over ``interval`` seconds, the hungriest first: what drains the battery?

    ::

        for use in macos.system.energy_usage()[:5]:
            print(use.process, "{:.2f} W".format(use.watts))   # Google Chrome Helper 1.84 W

    It also tells the bytes each read and wrote on disk. Power is measured
    by Apple silicon Macs; on Intel Macs it reads 0. Only this user's
    processes are seen, as with :func:`processes`. A macOS too old to
    report it (``rusage_info_v6``, macOS 12) raises
    :class:`~macos.errors.NotSupportedError`.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    require_macos()
    lib, _ = _libproc()
    started = time.monotonic()
    before = {pid: found for pid in _pids() for found in [_rusage(lib, pid)] if found}
    if not before and _rusage(lib, os.getpid()) is None:
        # Not even this very process could be read: the kernel doesn't know this version of the record.
        raise NotSupportedError("this version of macOS doesn't report processes' energy use")
    time.sleep(interval)
    elapsed = time.monotonic() - started
    usage = []
    for pid, (energy, read, written, started_at) in before.items():
        now = _rusage(lib, pid)
        if now is None or now[3] != started_at:
            continue  # gone, or another process took its pid
        process = _read_process(pid)
        if process is None:
            continue
        usage.append(
            EnergyUsage(
                pid=pid,
                process=process.name,
                watts=round((now[0] - energy) / 1e9 / elapsed, 3),
                disk_read=max(now[1] - read, 0),
                disk_written=max(now[2] - written, 0),
            )
        )
    return sorted(usage, key=lambda use: (use.watts, use.disk_read + use.disk_written), reverse=True)


# --- The GPU --------------------------------------------------------------------


@dataclass(frozen=True)
class GPUUsage:
    """How busy a graphics processor is."""

    name: str
    """Such as ``'AGXAcceleratorG14X'``: the driver's name for it."""
    percent: int
    """How busy it is, from 0 to 100, as Activity Monitor's GPU History shows."""
    memory: Optional[int]
    """Memory it uses, in bytes; ``None`` when its driver doesn't say."""


def gpu_usage() -> List[GPUUsage]:
    """
    How busy each graphics processor is, as Activity Monitor's GPU History shows.

    ::

        macos.system.gpu_usage()   # [GPUUsage(name='AGXAcceleratorG14X', percent=37, memory=406667264)]

    Handy to watch a local AI model or a game. No permission is needed.
    """
    require_macos()
    io = _iokit.lib()
    iterator = ctypes.c_uint32()
    # The graphics drivers register as IOAccelerator; 0 is kIOMainPortDefault.
    if io.IOServiceGetMatchingServices(0, io.IOServiceMatching(b"IOAccelerator"), ctypes.byref(iterator)) != 0:
        return []
    found = []
    try:
        while True:
            service = io.IOIteratorNext(iterator.value)
            if not service:
                break
            try:
                with _cf.owned(_cf.string("PerformanceStatistics")) as key, _cf.owned(
                    io.IORegistryEntryCreateCFProperty(service, key, None, 0)
                ) as statistics:
                    values = _cf.to_python(statistics) if statistics else None
                if not isinstance(values, dict) or "Device Utilization %" not in values:
                    continue
                name = ctypes.create_string_buffer(128)  # io_name_t
                io.IOObjectGetClass(service, name)
                memory = values.get("In use system memory", values.get("vramUsedBytes"))
                found.append(
                    GPUUsage(
                        name=name.value.decode("utf-8", "replace"),
                        percent=int(values["Device Utilization %"]),
                        memory=int(memory) if memory is not None else None,
                    )
                )
            finally:
                io.IOObjectRelease(service)
    finally:
        io.IOObjectRelease(iterator.value)
    return found


# --- Disk health --------------------------------------------------------------------


@dataclass(frozen=True)
class DiskHealth:
    """A physical disk, and whether it reports it's failing."""

    device: str
    """Such as ``'disk0'``."""
    name: str
    """Its model, such as ``'APPLE SSD AP0512Z'``."""
    size: int
    """In bytes."""
    internal: bool
    solid_state: Optional[bool]
    smart: Optional[str]
    """Its SMART status: ``'verified'`` (healthy), ``'failing'``, or ``None`` when the disk doesn't report one.

    Most USB disks don't."""


_DISKUTIL_TIMEOUT = 60.0  # seconds for diskutil to describe a disk


def disk_health() -> List[DiskHealth]:
    """
    The Mac's physical disks and their SMART status, which warns when a disk is about to fail.

    ::

        for disk in macos.system.disk_health():
            if disk.smart == "failing":
                print("Back up", disk.name, "now")

    Goes through ``diskutil``. Many USB disks don't report a status. A
    disk that doesn't answer within a minute (a failing one may not) raises
    :class:`~macos.errors.CommandTimeoutError`.
    """
    import plistlib

    require_macos()
    listed = plistlib.loads(_run(["diskutil", "list", "-plist", "physical"], timeout=_DISKUTIL_TIMEOUT).encode())
    disks = []
    for device in listed.get("WholeDisks", []):
        info = plistlib.loads(_run(["diskutil", "info", "-plist", device], timeout=_DISKUTIL_TIMEOUT).encode())
        status = str(info.get("SMARTStatus") or "").lower()
        disks.append(
            DiskHealth(
                device=device,
                name=str(info.get("MediaName") or info.get("IORegistryEntryName") or device).strip(),
                size=int(info.get("Size") or info.get("TotalSize") or 0),
                internal=bool(info.get("Internal")),
                solid_state=info.get("SolidState"),
                smart=status if status in ("verified", "failing") else None,
            )
        )
    return disks


# --- Crash reports ----------------------------------------------------------------

_REPORT_FOLDERS = ("~/Library/Logs/DiagnosticReports", "/Library/Logs/DiagnosticReports")
_CRASHES = {"309", "109"}  # the .ips reports' bug_type for a crash, in the current format and the old one


@dataclass(frozen=True)
class CrashReport:
    """An app or a process that crashed, as the report macOS wrote tells."""

    app: str
    version: Optional[str]
    date: Optional[datetime]
    reason: Optional[str]
    """What stopped it, such as ``'EXC_BAD_ACCESS (SIGSEGV)'``."""
    path: Path
    """The report, to read or share with the app's developers."""


def _crash_report(path: Path, app: Optional[str] = None) -> Optional[CrashReport]:
    """The crash a report tells, or ``None`` for another kind of report, a broken one, or (with ``app``) another app's."""
    try:
        with open(path, encoding="utf-8", errors="replace") as file:
            header = json.loads(file.readline())
            if not isinstance(header, dict) or str(header.get("bug_type")) not in _CRASHES:
                return None
            named = header.get("app_name") or header.get("name")
            if app and named and str(named).lower() != app.lower():
                return None  # another app's: its body, often hundreds of kilobytes, isn't read
            try:
                body = json.loads(file.read())
            except ValueError:
                body = {}
    except (OSError, ValueError):
        return None

    def part(value: object) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}  # a corrupt report must not break the listing

    body = part(body)
    exception = part(body.get("exception"))
    reason = exception.get("type")
    if reason and exception.get("signal"):
        reason = "{} ({})".format(reason, exception["signal"])
    elif not reason:
        reason = part(body.get("termination")).get("indicator")
    date = None
    try:
        date = datetime.strptime(str(header.get("timestamp")), "%Y-%m-%d %H:%M:%S.%f %z")
    except ValueError:
        pass
    return CrashReport(
        app=str(header.get("app_name") or header.get("name") or body.get("procName") or path.stem),
        version=header.get("app_version") or None,
        date=date,
        reason=reason,
        path=path,
    )


def _before(date: datetime, cutoff: datetime) -> bool:
    """Whether ``date`` (with its offset) is before ``cutoff``, which is taken as this Mac's local time when it has none."""
    if cutoff.tzinfo is None:
        return date.astimezone().replace(tzinfo=None) < cutoff  # the report's instant, on the local clock
    return date < cutoff


def crash_reports(app: Optional[str] = None, *, since: Optional[datetime] = None) -> List[CrashReport]:
    """
    The crashes macOS recorded, the latest first: which app, when, and why.

    ::

        for crash in macos.system.crash_reports(since=datetime.now() - timedelta(days=7)):
            print(crash.date, crash.app, crash.reason)   # 2026-09-29 13:55 Safari EXC_BAD_ACCESS (SIGSEGV)

    ``app`` keeps one app's, by name (case doesn't matter); ``since`` is
    this Mac's local time unless it carries a time zone. It reads the
    reports in ``~/Library/Logs/DiagnosticReports``, and the system's that
    this user may read. macOS deletes them after a while.
    """
    require_macos()
    found = []
    for folder in _REPORT_FOLDERS:
        root = Path(folder).expanduser()
        try:
            candidates = list(root.glob("*.ips"))
        except OSError:
            continue
        for path in candidates:
            report = _crash_report(path, app)
            if report is None or (app and report.app.lower() != app.lower()):
                continue
            if since and report.date and _before(report.date, since):
                continue
            found.append(report)
    return sorted(found, key=lambda report: (report.date is not None, report.date), reverse=True)


# --- The system log -----------------------------------------------------------------

_LOG_LEVELS = {"default": "Default", "info": "Info", "debug": "Debug", "error": "Error", "fault": "Fault"}


@dataclass(frozen=True)
class LogEntry:
    """A message in the system log."""

    date: Optional[datetime]
    process: str
    pid: Optional[int]
    subsystem: Optional[str]
    """Such as ``'com.apple.bluetooth'``."""
    category: Optional[str]
    level: str
    """``'default'``, ``'info'``, ``'debug'``, ``'error'`` or ``'fault'``."""
    message: str


def _quoted(text: str) -> str:
    """``text`` as a string in a log predicate."""
    return '"{}"'.format(text.replace("\\", "\\\\").replace('"', '\\"'))


def _log_entry(line: str) -> Optional[LogEntry]:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if event.get("eventType") != "logEvent":
        return None
    date = None
    try:
        date = datetime.strptime(event.get("timestamp", ""), "%Y-%m-%d %H:%M:%S.%f%z")
    except ValueError:
        pass
    pid = event.get("processID")
    return LogEntry(
        date=date,
        process=os.path.basename(event.get("processImagePath") or "") or "?",
        pid=int(pid) if str(pid).isdigit() else None,
        subsystem=event.get("subsystem") or None,
        category=event.get("category") or None,
        level=str(event.get("messageType") or "Default").lower(),
        message=event.get("eventMessage") or "",
    )


def logs(
    *,
    process: Optional[str] = None,
    subsystem: Optional[str] = None,
    contains: Optional[str] = None,
    level: Optional[str] = None,
    last: Union[str, timedelta] = "10m",
    limit: Optional[int] = 1000,
    timeout: Optional[float] = 120.0,
) -> List[LogEntry]:
    """
    Read the system log (Console's), oldest first, filtered by process, subsystem, text or level.

    ::

        for entry in macos.system.logs(process="Safari", level="error", last="1h"):
            print(entry.date, entry.message)

    ``contains`` keeps messages holding a text (case doesn't matter);
    ``level`` keeps messages from that level up: ``"debug"``, ``"info"``,
    ``"default"``, ``"error"`` or ``"fault"``. ``last`` is how far back, as
    ``"30s"``, ``"10m"``, ``"2h"``, ``"1d"`` or a :class:`~datetime.timedelta`.
    The log is large (thousands of messages a minute): filter it, and
    ``limit`` stops at that many messages (``None`` for all). Goes through
    ``log show``; some messages hide private data as ``<private>``. Reading
    days of an unfiltered log takes long: past ``timeout`` seconds (``None``
    to wait for as long as it takes) ``log show`` is stopped and
    :class:`~macos.errors.CommandTimeoutError` raised.
    """
    import subprocess
    import tempfile
    import threading

    if isinstance(last, timedelta):
        last = "{}s".format(max(1, int(last.total_seconds())))
    if not re.fullmatch(r"\d+[smhd]", last):
        raise ValueError("last must be like '30s', '10m', '2h' or '1d', or a timedelta, not {!r}".format(last))
    if level is not None and level not in _LOG_LEVELS:
        raise ValueError("level must be one of {}, not {!r}".format(", ".join(_LOG_LEVELS), level))
    if limit is not None and limit < 1:
        raise ValueError("limit must be 1 or more, or None, not {}".format(limit))
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive, or None, not {}".format(timeout))
    require_macos()
    conditions = []
    if process:
        conditions.append("process == {}".format(_quoted(process)))
    if subsystem:
        conditions.append("subsystem == {}".format(_quoted(subsystem)))
    if contains:
        conditions.append("eventMessage CONTAINS[c] {}".format(_quoted(contains)))
    if level == "error":
        conditions.append("messageType >= error")  # errors and faults: a keyword, not a string
    elif level == "fault":
        conditions.append("messageType == fault")
    args = ["/usr/bin/log", "show", "--style", "ndjson", "--last", last]
    if level in ("info", "debug"):
        args.append("--" + level)  # log show leaves them out unless asked
    if conditions:
        args += ["--predicate", " AND ".join(conditions)]
    entries: List[LogEntry] = []
    # Its errors go to a file, not a second pipe: a pipe only read once the output ends would fill up
    # (64 KB) on a chatty failure, and log show would wait on it forever while we wait on the output.
    with tempfile.TemporaryFile() as errors_file:
        reader = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors_file, text=True, encoding="utf-8")
        assert reader.stdout is not None
        stopped = False  # by us, at the limit: not a failure
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            reader.kill()  # its output ends, and so does the loop below

        timer = threading.Timer(timeout, expire) if timeout is not None else None
        if timer is not None:
            timer.daemon = True
            timer.start()
        try:
            for line in reader.stdout:
                entry = _log_entry(line) if line.startswith("{") else None
                if entry:
                    entries.append(entry)
                    if limit is not None and len(entries) >= limit:
                        stopped = True
                        break
        finally:
            if timer is not None:
                timer.cancel()
            if stopped or expired.is_set():
                reader.kill()
            reader.wait()
            reader.stdout.close()
        errors_file.seek(0)
        errors = errors_file.read().decode("utf-8", "replace")
    if expired.is_set() and not stopped:
        raise CommandTimeoutError(args, timeout or 0)
    if not stopped and reader.returncode != 0:
        raise CommandError(args, reader.returncode, errors)
    return entries


# --- USB devices ---------------------------------------------------------------------

_USB_SPEEDS = {0: "low", 1: "full", 2: "high", 3: "super", 4: "super_plus"}  # 1.5, 12, 480 Mbit/s, 5 and 10+ Gbit/s
_HUB = 9  # bDeviceClass of a hub


@dataclass(frozen=True)
class USBDevice:
    """A device connected over USB."""

    name: Optional[str]
    vendor: Optional[str]
    vendor_id: Optional[int]
    product_id: Optional[int]
    serial: Optional[str]
    speed: Optional[str]
    """``'low'``, ``'full'`` (USB 1), ``'high'`` (USB 2), ``'super'`` or ``'super_plus'`` (USB 3)."""
    is_hub: bool


def _usb_device(properties: Dict[str, Any]) -> USBDevice:
    def text(*keys: str) -> Optional[str]:
        for key in keys:
            value = properties.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def number(key: str) -> Optional[int]:
        value = properties.get(key)
        return int(value) if isinstance(value, int) else None

    speed = number("Device Speed")
    return USBDevice(
        name=text("USB Product Name", "kUSBProductString"),
        vendor=text("USB Vendor Name", "kUSBVendorString"),
        vendor_id=number("idVendor"),
        product_id=number("idProduct"),
        serial=text("USB Serial Number", "kUSBSerialNumberString"),
        speed=_USB_SPEEDS.get(speed) if speed is not None else None,
        is_hub=number("bDeviceClass") == _HUB,
    )


def usb_devices() -> List[USBDevice]:
    """
    The devices connected over USB: name, maker, IDs and speed.

    ::

        [device.name for device in macos.system.usb_devices()]   # ['USB Keyboard', 'Samsung T7', ...]

    Hubs are listed too (``is_hub``), since a device behind a slow hub runs
    slowly. Built-in keyboards and trackpads on recent Macs aren't USB, so
    they're not listed. To know when a device comes or goes, see
    :mod:`macos.events`.
    """
    require_macos()
    io = _iokit.lib()
    iterator = ctypes.c_uint32()
    if io.IOServiceGetMatchingServices(0, io.IOServiceMatching(b"IOUSBHostDevice"), ctypes.byref(iterator)) != 0:
        return []
    found = []
    try:
        while True:
            service = io.IOIteratorNext(iterator.value)
            if not service:
                break
            try:
                properties = _cf.CFTypeRef()
                if io.IORegistryEntryCreateCFProperties(service, ctypes.byref(properties), None, 0) == 0 and properties.value:
                    with _cf.owned(properties.value):
                        values = _cf.to_python(properties.value)
                    if isinstance(values, dict):
                        found.append(_usb_device(values))
            finally:
                io.IOObjectRelease(service)
    finally:
        io.IOObjectRelease(iterator.value)
    return found


# --- Startup items --------------------------------------------------------------------

_STARTUP_FOLDERS = (
    ("~/Library/LaunchAgents", "agent", False),
    ("/Library/LaunchAgents", "agent", True),
    ("/Library/LaunchDaemons", "daemon", True),
)


@dataclass(frozen=True)
class StartupItem:
    """Something macOS starts by itself: a launch agent (in the user's session) or a daemon (for the whole system)."""

    label: str
    """Its name for launchd, such as ``'com.google.keystone.agent'``."""
    kind: str
    """``'agent'`` (runs as a user, in their session) or ``'daemon'`` (runs as the system, before anyone logs in)."""
    for_all_users: bool
    """Installed for every user of the Mac, rather than for this one."""
    program: Optional[str]
    """What it runs."""
    arguments: Tuple[str, ...]
    run_at_load: bool
    """Started when loaded: at login for an agent, at startup for a daemon."""
    keep_alive: bool
    """Started again whenever it stops."""
    enabled: bool
    """Not turned off, by its own file or by launchctl."""
    running: Optional[bool]
    """Running now; ``None`` when launchd didn't say."""
    path: Path
    """Its description file (a .plist)."""


def _launchd_state(domain: str, label: str) -> Optional[bool]:
    """Whether a job runs now: ``True``, ``False`` (loaded, not running, or not loaded), or ``None`` if launchd won't say."""
    try:
        output = _run(["launchctl", "print", "{}/{}".format(domain, label)])
    except CommandError as error:
        return False if "Could not find service" in (error.stderr or "") else None
    found = re.search(r"^\s*state = (\S+)", output, re.M)
    return found.group(1) == "running" if found else None


def _disabled(domain: str) -> Dict[str, bool]:
    """launchctl's own switches: label -> disabled."""
    try:
        output = _run(["launchctl", "print-disabled", domain])
    except CommandError:
        return {}
    # Written as words or as booleans, depending on the macOS version: "disabled" and true mean off.
    found = re.findall(r'"([^"]+)"\s*=>\s*(enabled|disabled|true|false)', output)
    return {label: state in ("disabled", "true") for label, state in found}


def startup_items() -> List[StartupItem]:
    """
    What macOS starts by itself, besides the apps opened at login: launch agents and daemons.

    ::

        for item in macos.system.startup_items():
            if item.enabled:
                print(item.label, item.program)   # com.google.keystone.agent /Library/Google/...

    Agents run in the user's session; daemons run for the whole system. It
    reads the user's and the Mac's ``LaunchAgents`` and ``LaunchDaemons``
    folders, leaving out Apple's own in ``/System``. Jobs made with
    :mod:`macos.schedule` are among the agents. For the apps opened at
    login, see :func:`macos.apps.login_items`.
    """
    import plistlib

    require_macos()
    user_domain = "gui/{}".format(os.getuid())
    switches = {"agent": _disabled(user_domain), "daemon": _disabled("system")}
    found = []
    for folder, kind, shared in _STARTUP_FOLDERS:
        root = Path(folder).expanduser()
        try:
            files = sorted(root.glob("*.plist"))
        except OSError:
            continue
        for path in files:
            try:
                info = plistlib.loads(path.read_bytes())
            except (OSError, ValueError, plistlib.InvalidFileException):
                continue
            if not isinstance(info, dict) or not info.get("Label"):
                continue
            label = str(info["Label"])
            listed = info.get("ProgramArguments")
            # Only an array holds arguments: a string or a number there is a broken file, not letters to split.
            arguments = tuple(str(argument) for argument in listed) if isinstance(listed, list) else ()
            program = info.get("Program") or (arguments[0] if arguments else None)
            keep_alive = info.get("KeepAlive")
            # launchctl's own switch, when it has one, wins over the file's Disabled key, either way.
            if label in switches[kind]:
                enabled = not switches[kind][label]
            else:
                enabled = not info.get("Disabled", False)
            found.append(
                StartupItem(
                    label=label,
                    kind=kind,
                    for_all_users=shared,
                    program=str(program) if program else None,
                    arguments=arguments,
                    run_at_load=bool(info.get("RunAtLoad", False)),
                    keep_alive=bool(keep_alive) if not isinstance(keep_alive, dict) else True,
                    enabled=enabled,
                    running=_launchd_state(user_domain if kind == "agent" else "system", label),
                    path=path,
                )
            )
    return found
