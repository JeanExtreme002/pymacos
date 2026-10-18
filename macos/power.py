# -*- coding: utf-8 -*-

"""
Battery status, keeping the Mac awake, and what keeps it awake.

::

    battery = macos.power.battery()
    print(battery.percent, battery.charging)

    with macos.power.keep_awake():
        train_model()       # the Mac won't go to sleep meanwhile

    macos.power.sleep_blockers()   # [SleepBlocker(process='zoom.us', reason='Meeting in progress', ...)]

Both talk to IOKit directly: the battery comes from the same power-source
information as the menu bar icon, and ``keep_awake`` holds a power assertion,
like the ``caffeinate`` command does.
"""

import ctypes
import functools
import inspect
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar

from . import _cf, _iokit, _objc
from ._system import framework, run as _run
from .errors import MacOSError

__all__ = [
    "Battery",
    "battery",
    "low_power_mode",
    "keep_awake",
    "sleep",
    "sleep_display",
    "Adapter",
    "adapter",
    "SleepBlocker",
    "sleep_blockers",
]

_ASSERTION_ON = 255  # kIOPMAssertionLevelOn


def _battery_registry(*names: str) -> Dict[str, Optional[int]]:
    """Integer properties of the AppleSmartBattery service (``None`` when missing)."""
    io = _iokit.lib()
    service = io.IOServiceGetMatchingService(_iokit.MAIN_PORT, io.IOServiceMatching(b"AppleSmartBattery"))
    values: Dict[str, Optional[int]] = {name: None for name in names}
    if not service:
        return values
    try:
        for name in names:
            with _cf.owned(_cf.string(name)) as key:
                with _cf.owned(io.IORegistryEntryCreateCFProperty(service, key, None, 0)) as ref:
                    values[name] = _cf.to_int(ref)
    finally:
        io.IOObjectRelease(service)
    return values


def _health() -> Tuple[Optional[int], Optional[int]]:
    data = _battery_registry("CycleCount", "DesignCapacity", "NominalChargeCapacity", "AppleRawMaxCapacity", "MaxCapacity")
    design = data["DesignCapacity"]
    # The nominal charge capacity, which macOS corrects on its own before
    # System Settings shows it; older Macs only have the raw maximum (Apple
    # Silicon) or report MaxCapacity in mAh (Intel).
    full = data["NominalChargeCapacity"] or data["AppleRawMaxCapacity"]
    if full is None and (data["MaxCapacity"] or 0) > 100:
        full = data["MaxCapacity"]
    # A new battery can hold slightly more than its design capacity; System
    # Settings shows that as 100%.
    health = min(100, round(full * 100 / design)) if full and design else None
    return data["CycleCount"], health


@dataclass(frozen=True)
class Battery:
    """A snapshot of the internal battery."""

    percent: int
    """Charge level, from 0 to 100."""
    charging: bool
    """Whether it is charging right now (``False`` once full, even if plugged in)."""
    plugged_in: bool
    """Whether the Mac is running on AC power."""
    time_remaining: Optional[timedelta]
    """Time until empty on battery, or until full while charging.
    ``None`` while macOS is still estimating, or when plugged in but not charging."""
    cycle_count: Optional[int] = None
    """How many full charge cycles the battery has gone through."""
    health: Optional[int] = None
    """Maximum capacity compared with when it was new, in percent: the full
    charge the battery holds now over its design capacity. System Settings ›
    Battery › Battery Health applies its own correction, so it can show a
    point or two more."""


def _minutes(value: Optional[int]) -> Optional[timedelta]:
    # IOKit reports -1 while it is still estimating.
    return timedelta(minutes=value) if value is not None and value >= 0 else None


def battery() -> Optional[Battery]:
    """Return the internal battery's status, or ``None`` on a Mac without one (e.g. a Mac mini)."""
    io = _iokit.lib()
    with _cf.owned(io.IOPSCopyPowerSourcesInfo()) as info, _cf.owned(io.IOPSCopyPowerSourcesList(info)) as sources:
        for source in _cf.items(sources):
            description = io.IOPSGetPowerSourceDescription(info, source)
            if _cf.to_str(_cf.lookup(description, "Type")) != "InternalBattery":
                continue
            if not _cf.to_bool(_cf.lookup(description, "Is Present")):
                continue

            current = _cf.to_int(_cf.lookup(description, "Current Capacity")) or 0
            maximum = _cf.to_int(_cf.lookup(description, "Max Capacity")) or 100
            charging = _cf.to_bool(_cf.lookup(description, "Is Charging"))
            plugged_in = _cf.to_str(_cf.lookup(description, "Power Source State")) == "AC Power"
            key = "Time to Full Charge" if charging else "Time to Empty"
            remaining = _minutes(_cf.to_int(_cf.lookup(description, key)))

            cycle_count, health = _health()
            return Battery(
                percent=round(current * 100 / maximum) if maximum else 0,
                charging=charging,
                plugged_in=plugged_in,
                time_remaining=remaining if charging or not plugged_in else None,
                cycle_count=cycle_count,
                health=health,
            )
    return None


def low_power_mode() -> bool:
    """
    Whether Low Power Mode is on (System Settings › Battery), making the Mac slower to save energy.

    A long job can check it and lighten its work. Always ``False`` before macOS 12, which didn't have it.
    """
    framework("Foundation")
    with _objc.autorelease_pool():
        info = _objc.send(_objc.cls("NSProcessInfo"), "processInfo")
        has_it = _objc.send(
            info, "respondsToSelector:", _objc.sel("isLowPowerModeEnabled"), argtypes=(_objc.SEL,), restype=_objc.BOOL
        )
        return bool(has_it and _objc.send(info, "isLowPowerModeEnabled", restype=_objc.BOOL))


_Function = TypeVar("_Function", bound=Callable[..., Any])


class _KeepAwake:
    """What :func:`keep_awake` returns: a context manager, sync or async, and a decorator."""

    def __init__(self, display: bool, reason: str) -> None:
        self._display = display
        self._reason = reason
        # One assertion per entry, so the same object can be entered again
        # while it's held (nested blocks) and each exit releases its own.
        self._held: List[int] = []

    def __enter__(self) -> None:
        io = _iokit.lib()
        kind = "PreventUserIdleDisplaySleep" if self._display else "PreventUserIdleSystemSleep"
        assertion = ctypes.c_uint32()
        with _cf.owned(_cf.string(kind)) as kind_ref, _cf.owned(_cf.string(self._reason)) as reason_ref:
            status = io.IOPMAssertionCreateWithName(kind_ref, _ASSERTION_ON, reason_ref, ctypes.byref(assertion))
        if status != _iokit.SUCCESS:
            raise MacOSError("could not create the power assertion (IOReturn {:#x})".format(status & 0xFFFFFFFF))
        self._held.append(assertion.value)

    def __exit__(
        self, kind: Optional[Type[BaseException]], error: Optional[BaseException], traceback: Optional[TracebackType]
    ) -> None:
        _iokit.lib().IOPMAssertionRelease(self._held.pop())

    async def __aenter__(self) -> None:
        self.__enter__()

    async def __aexit__(
        self, kind: Optional[Type[BaseException]], error: Optional[BaseException], traceback: Optional[TracebackType]
    ) -> None:
        self.__exit__(kind, error, traceback)

    def __call__(self, function: _Function) -> _Function:
        if inspect.isgeneratorfunction(function) or inspect.isasyncgenfunction(function):
            # Calling one only makes the generator: nothing would be held while
            # it runs, and holding it between items could keep the Mac up for good.
            raise TypeError("keep_awake() can't decorate a generator function: use it as a with block inside")
        display, reason = self._display, self._reason
        wrapper: Callable[..., Any]
        if inspect.iscoroutinefunction(function):
            # Calling it only makes the coroutine: hold the assertion while it's awaited.
            @functools.wraps(function)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                async with _KeepAwake(display, reason):
                    return await function(*args, **kwargs)

        else:

            @functools.wraps(function)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                with _KeepAwake(display, reason):
                    return function(*args, **kwargs)

        return wrapper  # type: ignore[return-value]


def keep_awake(*, display: bool = False, reason: str = "pymacos keep_awake") -> _KeepAwake:
    """
    Keep the Mac from going to sleep while the block runs.

    By default the display may still turn off; ``display=True`` keeps it on
    too. ``reason`` shows up in ``pmset -g assertions`` and Activity Monitor.
    It works as an ``async with`` block, and as a decorator as well::

        @macos.power.keep_awake()
        def backup():
            ...

    On an ``async def`` function the Mac stays awake while the coroutine is
    awaited. A generator function raises :class:`TypeError`: use a ``with``
    block inside it instead. A ``reason`` that isn't a string raises
    :class:`TypeError`, and one that can't be encoded as UTF-8 (a lone
    surrogate) :class:`ValueError`.

    Closing the lid still puts a laptop to sleep, as with ``caffeinate``.
    """
    if not isinstance(reason, str):
        raise TypeError("reason must be a str, not {}".format(type(reason).__name__))
    try:
        reason.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("reason can't be encoded as UTF-8: {!r}".format(reason)) from None
    return _KeepAwake(display, reason)


_PMSET_TIMEOUT = 30.0  # seconds: pmset only asks for the sleep, and answers at once


def sleep() -> None:
    """Put the Mac to sleep right away, like  › Sleep."""
    _run(["pmset", "sleepnow"], timeout=_PMSET_TIMEOUT)


def sleep_display() -> None:
    """
    Turn the display off right away; the Mac keeps running.

    With *Require password after screen saver begins or display is turned off*
    set to *Immediately* (the default), this also locks the screen.
    """
    _run(["pmset", "displaysleepnow"], timeout=_PMSET_TIMEOUT)


@dataclass(frozen=True)
class Adapter:
    """The power adapter (charger) the Mac is plugged into."""

    watts: Optional[int]
    """What it can give, such as 96: a 30 W adapter charges a big laptop slowly."""
    name: Optional[str]
    """Such as ``'96W USB-C Power Adapter'``."""
    manufacturer: Optional[str]
    voltage: Optional[float]
    """In volts, as it's delivering now."""
    current: Optional[float]
    """In amperes, the most it's delivering now."""


def adapter() -> Optional[Adapter]:
    """
    The charger the Mac is plugged into, or ``None`` on battery (or on a desktop Mac, which has none to report).

    ::

        macos.power.adapter()   # Adapter(watts=96, name='96W USB-C Power Adapter', ...)
    """
    io = _iokit.lib()
    with _cf.owned(io.IOPSCopyExternalPowerAdapterDetails()) as details:
        found = _cf.to_python(details) if details else None
    return _adapter(found)


def _adapter(found: Any) -> Optional[Adapter]:
    """An :class:`Adapter` from the IOKit's description of it; ``None`` when there's none."""
    if not isinstance(found, dict) or not found:
        return None

    def number(key: str, scale: float = 1.0) -> Optional[float]:
        value = found.get(key)
        return round(float(value) / scale, 2) if isinstance(value, (int, float)) and value else None

    watts = found.get("Watts")
    return Adapter(
        watts=int(watts) if isinstance(watts, (int, float)) and watts else None,
        name=str(found.get("Name") or found.get("Description") or "") or None,
        manufacturer=found.get("Manufacturer") or None,
        voltage=number("Voltage", 1000),  # the IOKit gives millivolts
        current=number("Current", 1000),  # and milliamperes
    )


# The assertions that keep the Mac awake, and whether they keep the display on too, as powerd applies them
# (PMAssertions.c). Not UserIsActive, which is someone using the Mac, nor ExternalMedia, which only
# delays the deeper standby sleep. PreventSystemSleep, BackgroundTask (Time Machine) and the push
# service ones hold only on AC power or in dark wake; on battery pmset lists them all the same.
_KEEPS_AWAKE = {
    "PreventUserIdleSystemSleep": False,
    "NoIdleSleepAssertion": False,
    "SystemIsActive": False,
    "PreventSystemSleep": False,
    "DenySystemSleep": False,
    "InternalPreventSleep": False,
    "MaintenanceActivity": False,
    "NetworkClientActive": False,
    "BackgroundTask": False,
    "ApplePushServiceTask": False,
    "InteractivePushServiceTask": False,
    "PreventUserIdleDisplaySleep": True,
    "NoDisplaySleepAssertion": True,
    "InternalPreventDisplaySleep": True,
}


@dataclass(frozen=True)
class SleepBlocker:
    """A process keeping the Mac from going to sleep on its own."""

    pid: int
    process: str
    """Such as ``'caffeinate'`` or ``'zoom.us'``."""
    reason: str
    """What the process says it's doing, such as ``'Playing video'``."""
    display: bool
    """Whether it keeps the display on too, not only the Mac awake."""
    kind: str
    """The macOS name of the request, such as ``'PreventUserIdleSystemSleep'``."""
    since: Optional[datetime]
    until: Optional[datetime]
    """When it gives up by itself, or ``None`` when it holds until its process lets go."""


def sleep_blockers() -> List[SleepBlocker]:
    """
    The processes keeping the Mac from going to sleep, oldest first: the answer
    to "why doesn't my Mac sleep?", like ``pmset -g assertions``.

    ::

        for blocker in macos.power.sleep_blockers():
            print(blocker.process, blocker.reason)   # caffeinate  caffeinate command-line tool

    macOS itself shows up as ``powerd`` while the display is on. Apps playing
    sound or video, :func:`keep_awake` and ``caffeinate`` are the usual others,
    and File or Screen Sharing serving someone, or a Time Machine backup. Some
    of these keep the Mac awake only on AC power: like ``pmset``, the list has
    them on battery too.
    """
    io = _iokit.lib()
    found = _cf.CFTypeRef()
    status = io.IOPMCopyAssertionsByProcess(ctypes.byref(found))
    if status != _iokit.SUCCESS:
        raise MacOSError("could not read the power assertions (IOReturn {:#x})".format(status & 0xFFFFFFFF))
    with _cf.owned(found.value) as assertions:
        # The keys are process IDs, as numbers: not a property list, so each value converts on its own.
        by_process = [_cf.to_python(value) for value in _cf.values(assertions)]
    return _sleep_blockers(entry for entries in by_process if isinstance(entries, list) for entry in entries)


def _local(moment: Any) -> Optional[datetime]:
    """A property list date (UTC) on the local clock."""
    if not isinstance(moment, datetime):
        return None
    return moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _sleep_blockers(entries: Any) -> List[SleepBlocker]:
    blockers = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("AssertType")
        if kind not in _KEEPS_AWAKE or entry.get("AssertLevel", _ASSERTION_ON) != _ASSERTION_ON:
            continue
        since = _local(entry.get("AssertStartWhen"))
        timeout = entry.get("TimeoutSeconds")
        pid = entry.get("AssertPID")
        blockers.append(
            SleepBlocker(
                pid=pid if isinstance(pid, int) else 0,
                process=str(entry.get("Process Name") or ""),
                reason=str(entry.get("AssertName") or ""),
                display=_KEEPS_AWAKE[kind],
                kind=kind,
                since=since,
                until=since + timedelta(seconds=timeout) if since and isinstance(timeout, (int, float)) and timeout > 0 else None,
            )
        )
    return sorted(blockers, key=lambda blocker: (blocker.since or datetime.min, blocker.pid))
