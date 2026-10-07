# -*- coding: utf-8 -*-

"""
SystemConfiguration over ctypes: reachability, the network interfaces and
configd's dynamic store, with every signature the package uses declared once.

``framework("SystemConfiguration")`` is one cached handle: two modules that
declared ``SCDynamicStoreCreate`` each on their own (one with a callback type,
one with a plain pointer) were rewriting each other's ``argtypes``. They ask
:func:`lib` instead.
"""

import ctypes
from functools import lru_cache

from ._system import framework


class SockaddrIn(ctypes.Structure):
    """``struct sockaddr_in``, for the reachability of an IPv4 address."""

    _fields_ = [
        ("sin_len", ctypes.c_uint8),
        ("sin_family", ctypes.c_uint8),
        ("sin_port", ctypes.c_uint16),
        ("sin_addr", ctypes.c_uint32),
        ("sin_zero", ctypes.c_char * 8),
    ]


STORE_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
"""``SCDynamicStoreCallBack``: ``(store, changed keys, info)``."""


@lru_cache(maxsize=None)
def lib() -> ctypes.CDLL:
    sc = framework("SystemConfiguration")
    pointer = ctypes.c_void_p
    signatures = {
        # Reachability: is there a route out?
        "SCNetworkReachabilityCreateWithAddress": ((pointer, ctypes.POINTER(SockaddrIn)), pointer),
        "SCNetworkReachabilityGetFlags": ((pointer, ctypes.POINTER(ctypes.c_uint32)), ctypes.c_bool),
        # The interfaces, and their names in System Settings.
        "SCNetworkInterfaceCopyAll": ((), pointer),
        "SCNetworkInterfaceGetBSDName": ((pointer,), pointer),
        "SCNetworkInterfaceGetLocalizedDisplayName": ((pointer,), pointer),
        "SCNetworkInterfaceGetInterfaceType": ((pointer,), pointer),
        # The dynamic store. The callback is a plain pointer: a STORE_CALLBACK
        # passes as one, and so does None, for a store nobody watches.
        "SCDynamicStoreCreate": ((pointer, pointer, pointer, pointer), pointer),
        "SCDynamicStoreCopyValue": ((pointer, pointer), pointer),
        "SCDynamicStoreSetNotificationKeys": ((pointer, pointer, pointer), ctypes.c_bool),
        "SCDynamicStoreCreateRunLoopSource": ((pointer, pointer, ctypes.c_long), pointer),
        "SCDynamicStoreCopyProxies": ((pointer,), pointer),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(sc, name)
        function.argtypes = argtypes
        function.restype = restype
    return sc
