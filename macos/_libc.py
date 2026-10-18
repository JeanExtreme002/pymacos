# -*- coding: utf-8 -*-

"""
libSystem over ctypes: the C library, libproc and the Mach calls the package
uses, loaded once with every signature declared here.

Each ``ctypes.CDLL`` handle keeps its own function objects, so a library
loaded in several modules had its ``argtypes`` set (or forgotten) in each, and
``CDLL(None)`` loaded afresh on every call re-declared them each time. Every
module asks :func:`lib` instead.
"""

import ctypes
import os
from functools import lru_cache
from typing import List

from ._system import require_macos
from .errors import MacOSError

ENOATTR = 93
"""``errno.ENOATTR``, which only macOS's ``errno`` module has: the file doesn't have that extended attribute."""
XATTR_NOFOLLOW = 1
"""Act on a symbolic link itself, never on what it points to."""
XATTR_CREATE = 2
"""Set an extended attribute only if the file doesn't have it yet: ``EEXIST`` otherwise."""
ACL_TYPE_EXTENDED = 0x100
"""The only access control list type macOS has: ``acl_get_file`` and ``acl_set_file`` take it."""


class SockAddr(ctypes.Structure):
    """The start every ``sockaddr`` shares: its length, then its family."""

    _fields_ = [("len", ctypes.c_uint8), ("family", ctypes.c_uint8), ("data", ctypes.c_char * 14)]


class IfAddrs(ctypes.Structure):
    """``<ifaddrs.h>``'s ``struct ifaddrs``: one address of one interface, and the next."""


IfAddrs._fields_ = [
    ("next", ctypes.POINTER(IfAddrs)),
    ("name", ctypes.c_char_p),
    ("flags", ctypes.c_uint),
    ("address", ctypes.POINTER(SockAddr)),
    ("netmask", ctypes.c_void_p),
    ("destination", ctypes.c_void_p),
    ("data", ctypes.c_void_p),
]


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


@lru_cache(maxsize=None)
def lib() -> ctypes.CDLL:
    """libSystem, with ``errno`` kept for :func:`ctypes.get_errno`. libproc is part of it: there's no libproc.dylib."""
    require_macos()
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    size_p = ctypes.POINTER(ctypes.c_size_t)
    uint32_p = ctypes.POINTER(ctypes.c_uint32)
    signatures = {
        # Threads.
        "pthread_main_np": ((), ctypes.c_int),
        # Kernel values.
        "sysctlbyname": ((ctypes.c_char_p, ctypes.c_void_p, size_p, ctypes.c_void_p, ctypes.c_size_t), ctypes.c_int),
        "sysctl": (
            (ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p, size_p, ctypes.c_void_p, ctypes.c_size_t),
            ctypes.c_int,
        ),
        # Mach: the processor and memory statistics, and the clock's tick.
        "mach_host_self": ((), ctypes.c_uint32),
        "host_statistics": ((ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, uint32_p), ctypes.c_int),
        "host_statistics64": ((ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p, uint32_p), ctypes.c_int),
        "mach_timebase_info": ((ctypes.POINTER(_Timebase),), ctypes.c_int),
        # libproc: processes, their files and sockets, their resource use.
        "proc_listallpids": ((ctypes.c_void_p, ctypes.c_int), ctypes.c_int),
        "proc_pidinfo": ((ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int), ctypes.c_int),
        "proc_pidpath": ((ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32), ctypes.c_int),
        "proc_pidfdinfo": ((ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int), ctypes.c_int),
        "proc_pid_rusage": ((ctypes.c_int, ctypes.c_int, ctypes.c_void_p), ctypes.c_int),
        # Extended attributes.
        "getxattr": (
            (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int),
            ctypes.c_ssize_t,
        ),
        "listxattr": ((ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int), ctypes.c_ssize_t),
        "setxattr": (
            (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int),
            ctypes.c_int,
        ),
        "removexattr": ((ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int), ctypes.c_int),
        # Access control lists: a file's list is an opaque pointer, freed with acl_free.
        "acl_get_file": ((ctypes.c_char_p, ctypes.c_int), ctypes.c_void_p),
        "acl_set_file": ((ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p), ctypes.c_int),
        "acl_free": ((ctypes.c_void_p,), ctypes.c_int),
        # Network interfaces.
        "getifaddrs": ((ctypes.POINTER(ctypes.POINTER(IfAddrs)),), ctypes.c_int),
        "freeifaddrs": ((ctypes.POINTER(IfAddrs),), None),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(libc, name)
        function.argtypes = argtypes
        function.restype = restype
    return libc


@lru_cache(maxsize=None)
def tick() -> float:
    """
    How many nanoseconds a tick of this process's ``mach_absolute_time`` lasts (1 on Intel, not on Apple silicon).

    Not always libproc's tick for processor times: under Rosetta, macOS
    rescales an Intel Python's clock and answers 1/1, while libproc still
    counts the kernel's ticks. :func:`macos.system._kernel_tick` reads those
    from ``hw.tbfrequency``.
    """
    timebase = _Timebase()
    lib().mach_timebase_info(ctypes.byref(timebase))
    return timebase.numer / timebase.denom if timebase.denom else 1.0


def pids() -> List[int]:
    """
    Every running process's pid, this user's or not.

    Raises :class:`~macos.errors.MacOSError` when macOS won't list them, as
    in some sandboxes: an empty list would pass for nothing running.
    """
    libc = lib()
    # The process count can grow between the sizing call and the real one, so
    # leave headroom and retry if the buffer came back full.
    capacity = _listallpids(libc, None, 0) + 64
    while True:
        buffer = (ctypes.c_int * capacity)()
        count = _listallpids(libc, buffer, ctypes.sizeof(buffer))
        if count < capacity:
            return [pid for pid in buffer[:count] if pid > 0]
        capacity *= 2


def _listallpids(libc: ctypes.CDLL, buffer: object, size: int) -> int:
    # libproc reports a failure as 0 (not -1) with errno set; a real process
    # table always holds launchd and this process, so 0 is never an answer.
    ctypes.set_errno(0)
    count = libc.proc_listallpids(buffer, size)
    if count <= 0:
        error = ctypes.get_errno()
        reason = os.strerror(error) if error else "no processes listed"
        raise MacOSError("can't list the running processes: {}".format(reason))
    return int(count)
