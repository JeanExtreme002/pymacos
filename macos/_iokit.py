# -*- coding: utf-8 -*-

"""
IOKit over ctypes: the registry and its notifications, the power sources and
the power assertions, with every signature the package uses declared once.

``framework("IOKit")`` is one cached handle, so modules that declared the same
functions each on their own were setting the very same ``argtypes`` again,
and could disagree. They ask :func:`lib` instead.
"""

import ctypes
from functools import lru_cache

from . import _cf
from ._system import framework

MAIN_PORT = 0
"""``kIOMainPortDefault``: the port every IOKit lookup goes through."""
SUCCESS = 0
"""``kIOReturnSuccess``."""

POWER_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
"""``IOPowerSourceCallbackType``: ``(context)``."""
MATCHED_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32)
"""``IOServiceMatchingCallback``: ``(refcon, iterator)``."""


@lru_cache(maxsize=None)
def lib() -> ctypes.CDLL:
    io = framework("IOKit")
    ref, service = _cf.CFTypeRef, ctypes.c_uint32
    signatures = {
        # The registry: services and their properties.
        "IOServiceMatching": ((ctypes.c_char_p,), ref),
        "IOServiceGetMatchingService": ((ctypes.c_uint32, ref), service),
        "IOServiceGetMatchingServices": ((ctypes.c_uint32, ref, ctypes.POINTER(ctypes.c_uint32)), ctypes.c_int),
        "IOIteratorNext": ((ctypes.c_uint32,), service),
        "IOObjectRelease": ((ctypes.c_uint32,), ctypes.c_int),
        "IOObjectGetClass": ((service, ctypes.c_char_p), ctypes.c_int),
        "IORegistryEntryCreateCFProperty": ((service, ref, ref, ctypes.c_uint32), ref),
        "IORegistryEntryCreateCFProperties": ((service, ctypes.POINTER(ref), ref, ctypes.c_uint32), ctypes.c_int),
        # Power sources: the battery and the charger.
        "IOPSCopyPowerSourcesInfo": ((), ref),
        "IOPSCopyPowerSourcesList": ((ref,), ref),
        "IOPSGetPowerSourceDescription": ((ref, ref), ref),
        "IOPSCopyExternalPowerAdapterDetails": ((), ref),
        # Power assertions: what keeps the Mac awake.
        "IOPMAssertionCreateWithName": ((ref, ctypes.c_uint32, ref, ctypes.POINTER(ctypes.c_uint32)), ctypes.c_int),
        "IOPMAssertionRelease": ((ctypes.c_uint32,), ctypes.c_int),
        "IOPMCopyAssertionsByProcess": ((ctypes.POINTER(ref),), ctypes.c_int),
        "IOPSGetProvidingPowerSourceType": ((ref,), ref),
        "IOPSNotificationCreateRunLoopSource": ((POWER_CALLBACK, ctypes.c_void_p), ref),
        # Notifications: services appearing and going (USB devices...).
        "IONotificationPortCreate": ((ctypes.c_uint32,), ctypes.c_void_p),
        "IONotificationPortGetRunLoopSource": ((ctypes.c_void_p,), ref),
        "IONotificationPortDestroy": ((ctypes.c_void_p,), None),
        "IOServiceAddMatchingNotification": (
            (ctypes.c_void_p, ctypes.c_char_p, ref, MATCHED_CALLBACK, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)),
            ctypes.c_int,
        ),
        "IORegistryEntryGetName": ((service, ctypes.c_char_p), ctypes.c_int),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(io, name)
        function.argtypes = argtypes
        function.restype = restype
    return io
