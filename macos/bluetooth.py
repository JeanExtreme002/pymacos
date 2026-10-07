# -*- coding: utf-8 -*-

"""
Bluetooth power and devices: list them with their battery, connect and disconnect.

::

    macos.bluetooth.power()                  # True
    [device.name for device in macos.bluetooth.devices()]   # ['AirPods Pro', 'Magic Mouse']
    macos.bluetooth.connect("AirPods")
    macos.bluetooth.disconnect("AirPods")
    macos.bluetooth.set_power(False)

The devices come from ``system_profiler``, like System Information shows
them, so listing needs no permission. Connecting, disconnecting and switching
the power use IOBluetooth; macOS may ask to allow Bluetooth for the app
running Python (your terminal or IDE) the first time.
"""

import ctypes
import json
import time
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Dict, List, Set, Tuple, Union

from . import _objc
from ._system import PROFILER_TIMEOUT, framework, run as _run
from .errors import MacOSError, NotSupportedError

__all__ = ["Device", "power", "set_power", "devices", "connect", "disconnect"]

_BATTERY_KEYS = {
    "device_batteryLevelMain": "main",
    "device_batteryLevelLeft": "left",
    "device_batteryLevelRight": "right",
    "device_batteryLevelCase": "case",
}


@dataclass(frozen=True)
class Device:
    """A Bluetooth device paired with this Mac."""

    name: str
    address: str
    """Such as ``'E4:61:F4:CC:49:B2'``: the device's unique hardware address."""
    connected: bool
    kind: str
    """What it is, as macOS reports it, lowercased: ``'headphones'``, ``'mouse'``, ``'keyboard'``..."""
    battery: Dict[str, int] = field(default_factory=dict, hash=False)
    """
    Battery levels in percent, when the device reports them: ``{'main': 80}``, or
    ``{'left': 90, 'right': 85, 'case': 40}`` for AirPods. Empty otherwise.
    """


@lru_cache(maxsize=None)
def _bluetooth() -> ctypes.CDLL:
    bluetooth = framework("IOBluetooth")
    # The same private functions as the Bluetooth menu uses; there's no
    # public way to switch the power.
    for name in ("IOBluetoothPreferenceGetControllerPowerState", "IOBluetoothPreferenceSetControllerPowerState"):
        if not hasattr(bluetooth, name):
            raise NotSupportedError("this version of macOS doesn't expose the Bluetooth power")
    bluetooth.IOBluetoothPreferenceGetControllerPowerState.argtypes = ()
    bluetooth.IOBluetoothPreferenceGetControllerPowerState.restype = ctypes.c_int
    bluetooth.IOBluetoothPreferenceSetControllerPowerState.argtypes = (ctypes.c_int,)
    bluetooth.IOBluetoothPreferenceSetControllerPowerState.restype = None
    return bluetooth


def _require_controller() -> None:
    with _objc.autorelease_pool():
        if not _objc.send(_objc.cls("IOBluetoothHostController"), "defaultController"):
            raise NotSupportedError("this Mac has no Bluetooth")


def power() -> bool:
    """Whether Bluetooth is on. Raises :class:`~macos.errors.NotSupportedError` on a Mac without Bluetooth."""
    bluetooth = _bluetooth()
    _require_controller()
    return bool(bluetooth.IOBluetoothPreferenceGetControllerPowerState())


def set_power(on: bool, *, timeout: float = 10.0) -> None:
    """
    Turn Bluetooth on or off, like the switch in Control Center, and wait until it's done.

    Careful on a desktop Mac: turning it off disconnects a wireless keyboard
    and mouse. Raises :class:`~macos.errors.MacOSError` if the switch hasn't
    happened within ``timeout`` seconds.
    """
    if timeout <= 0:
        raise ValueError("timeout must be positive, not {}".format(timeout))
    bluetooth = _bluetooth()
    _require_controller()
    bluetooth.IOBluetoothPreferenceSetControllerPowerState(1 if on else 0)
    deadline = time.monotonic() + timeout
    while bool(bluetooth.IOBluetoothPreferenceGetControllerPowerState()) != bool(on):
        if time.monotonic() > deadline:
            raise MacOSError("Bluetooth didn't turn {} within {} seconds".format("on" if on else "off", timeout))
        time.sleep(0.1)


def _level(text: Any) -> Union[int, None]:
    try:
        return int(str(text).strip().rstrip("%"))
    except ValueError:
        return None


def _device(name: str, properties: Dict[str, Any], connected: bool) -> Device:
    battery = {}
    for key, part in _BATTERY_KEYS.items():
        level = _level(properties.get(key))
        if level is not None:
            battery[part] = level
    return Device(
        name=name,
        address=str(properties.get("device_address", "")).upper(),
        connected=connected,
        kind=str(properties.get("device_minorType", "unknown")).lower(),
        battery=battery,
    )


def _entries(entry: Any) -> List[Tuple[str, Dict[str, Any]]]:
    """
    The ``(name, properties)`` pairs of one item of a device list.

    macOS 14 and 15 write ``{"AirPods Pro": {...}}``; accept a flat
    ``{"device_name": ..., ...}`` too, and skip anything else.
    """
    if not isinstance(entry, dict):
        return []
    if isinstance(entry.get("device_name"), str):
        return [(entry["device_name"], entry)]
    return [(name, properties) for name, properties in entry.items() if isinstance(properties, dict)]


def devices() -> List[Device]:
    """
    Return the devices paired with this Mac, connected ones first.

    Each :class:`Device` has its ``name``, ``address``, whether it's
    ``connected``, its ``kind`` and, when the device reports it, its
    ``battery`` level.
    """
    output = _run(["system_profiler", "SPBluetoothDataType", "-json"], timeout=PROFILER_TIMEOUT)
    try:
        sections = json.loads(output).get("SPBluetoothDataType") or []
    except ValueError:
        raise MacOSError("system_profiler returned something unexpected") from None
    found: List[Device] = []
    seen: Set[Tuple[str, str]] = set()
    for section in sections:
        for key, connected in (("device_connected", True), ("device_not_connected", False)):
            for entry in section.get(key) or []:
                for name, properties in _entries(entry):
                    device = _device(name, properties, connected)
                    # The same device can be listed twice (connected, and in the
                    # paired list): one entry each. Some (a few accessories,
                    # older macOS) come without an address: tell those apart by
                    # name, or they'd all collapse into the first one.
                    identity = ("address", device.address) if device.address else ("name", device.name)
                    if identity not in seen:
                        seen.add(identity)
                        found.append(device)
    return found


def _find(target: Union[str, Device]) -> Device:
    """A paired device by :class:`Device`, address, full name or a unique part of its name."""
    if isinstance(target, Device):
        return target
    wanted = target.strip()
    if not wanted:
        # "" is part of every name: it would pick the only device paired.
        raise ValueError("name a Bluetooth device: its address, its name or part of it")
    paired = devices()
    for device in paired:
        if (device.address and wanted.upper().replace("-", ":") == device.address) or wanted == device.name:
            return device
    loose = [device for device in paired if wanted.casefold() in device.name.casefold()]
    if len(loose) == 1:
        return loose[0]
    names = ", ".join(repr(device.name) for device in paired) or "none"
    if not loose:
        raise ValueError("no paired Bluetooth device matches {!r}; paired: {}".format(target, names))
    raise ValueError("{!r} matches several paired devices ({}); use the full name".format(target, names))


def _connection(target: Union[str, Device], selector: str, verb: str, connected: bool, timeout: float) -> Device:
    if timeout <= 0:
        raise ValueError("timeout must be positive, not {}".format(timeout))
    device = _find(target)
    if not power():
        raise MacOSError("Bluetooth is off; turn it on with macos.bluetooth.set_power(True)")
    with _objc.autorelease_pool():
        handle = _objc.send(
            _objc.cls("IOBluetoothDevice"),
            "deviceWithAddressString:",
            _objc.nsstring(device.address),
            argtypes=(_objc.id,),
        )
        if not handle:
            raise MacOSError("macOS doesn't know the device {!r}".format(device.name))
        status = _objc.send(handle, selector, restype=ctypes.c_int)
        if status != 0:
            raise MacOSError("could not {} {!r} (IOReturn {:#x})".format(verb, device.name, status & 0xFFFFFFFF))
        # The request returns before the link changes: wait for it, or a
        # script that exits right away cancels it (the device stays connected).
        deadline = time.monotonic() + timeout
        while bool(_objc.send(handle, "isConnected", restype=_objc.BOOL)) != connected:
            if time.monotonic() > deadline:
                raise MacOSError("could not {} {!r} within {} seconds".format(verb, device.name, timeout))
            time.sleep(0.1)
    return replace(device, connected=connected)


def connect(device: Union[str, Device], *, timeout: float = 10.0) -> Device:
    """
    Connect a paired device and return it, like clicking it in the Bluetooth menu.

    ``device`` is a :class:`Device`, its address, its full name or part of
    its name when that matches only one device (``"AirPods"``). The device
    must be on and in range. This returns once the device is connected, or
    raises :class:`~macos.errors.MacOSError` after ``timeout`` seconds, or
    right away when Bluetooth is off.
    """
    return _connection(device, "openConnection", "connect to", True, timeout)


def disconnect(device: Union[str, Device], *, timeout: float = 10.0) -> Device:
    """
    Disconnect a paired device (it stays paired) and return it.

    ``device`` works as in :func:`connect`. This returns once the device is
    disconnected, or raises :class:`~macos.errors.MacOSError` after
    ``timeout`` seconds.
    """
    return _connection(device, "closeConnection", "disconnect", False, timeout)
