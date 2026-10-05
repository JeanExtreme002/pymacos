# -*- coding: utf-8 -*-

"""
CoreFoundation helpers over ctypes: creating and reading ``CFString``,
``CFData`` and ``CFDictionary`` values, and releasing them.

Every ``CF*Create``/``Copy`` result is owned by the caller and must be passed
to :func:`release`; :func:`owned` does that automatically at the end of a
``with`` block.
"""

import ctypes
from contextlib import contextmanager
from functools import lru_cache
import plistlib
from typing import Any, Dict, Iterator, List, Optional

from ._system import framework
from .errors import MacOSError

CFTypeRef = ctypes.c_void_p
CFIndex = ctypes.c_long

kCFStringEncodingUTF8 = 0x08000100


@lru_cache(maxsize=None)
def lib() -> ctypes.CDLL:
    cf = framework("CoreFoundation")

    cf.CFRelease.argtypes = (CFTypeRef,)
    cf.CFRelease.restype = None
    cf.CFRetain.argtypes = (CFTypeRef,)
    cf.CFRetain.restype = CFTypeRef
    cf.CFEqual.argtypes = (CFTypeRef, CFTypeRef)
    cf.CFEqual.restype = ctypes.c_bool

    cf.CFStringCreateWithBytes.argtypes = (CFTypeRef, ctypes.c_char_p, CFIndex, ctypes.c_uint32, ctypes.c_bool)
    cf.CFStringCreateWithBytes.restype = CFTypeRef
    cf.CFStringGetLength.argtypes = (CFTypeRef,)
    cf.CFStringGetLength.restype = CFIndex
    cf.CFStringGetMaximumSizeForEncoding.argtypes = (CFIndex, ctypes.c_uint32)
    cf.CFStringGetMaximumSizeForEncoding.restype = CFIndex
    cf.CFStringGetCString.argtypes = (CFTypeRef, ctypes.c_char_p, CFIndex, ctypes.c_uint32)
    cf.CFStringGetCString.restype = ctypes.c_bool

    cf.CFDataCreate.argtypes = (CFTypeRef, ctypes.c_char_p, CFIndex)
    cf.CFDataCreate.restype = CFTypeRef
    cf.CFDataGetLength.argtypes = (CFTypeRef,)
    cf.CFDataGetLength.restype = CFIndex
    cf.CFDataGetBytePtr.argtypes = (CFTypeRef,)
    cf.CFDataGetBytePtr.restype = ctypes.c_void_p

    cf.CFDictionaryCreate.argtypes = (
        CFTypeRef,
        ctypes.POINTER(CFTypeRef),
        ctypes.POINTER(CFTypeRef),
        CFIndex,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    cf.CFDictionaryCreate.restype = CFTypeRef

    cf.CFGetTypeID.argtypes = (CFTypeRef,)
    cf.CFGetTypeID.restype = ctypes.c_ulong
    cf.CFBooleanGetTypeID.argtypes = ()
    cf.CFBooleanGetTypeID.restype = ctypes.c_ulong
    cf.CFBooleanGetValue.argtypes = (CFTypeRef,)
    cf.CFBooleanGetValue.restype = ctypes.c_bool
    cf.CFStringGetTypeID.argtypes = ()
    cf.CFStringGetTypeID.restype = ctypes.c_ulong

    cf.CFPreferencesAppSynchronize.argtypes = (CFTypeRef,)
    cf.CFPreferencesAppSynchronize.restype = ctypes.c_bool
    cf.CFPreferencesCopyAppValue.argtypes = (CFTypeRef, CFTypeRef)
    cf.CFPreferencesCopyAppValue.restype = CFTypeRef

    cf.CFURLCopyFileSystemPath.argtypes = (CFTypeRef, ctypes.c_long)
    cf.CFURLCopyFileSystemPath.restype = CFTypeRef
    cf.CFURLCreateWithString.argtypes = (CFTypeRef, CFTypeRef, CFTypeRef)
    cf.CFURLCreateWithString.restype = CFTypeRef

    cf.CFArrayGetCount.argtypes = (CFTypeRef,)
    cf.CFArrayGetCount.restype = CFIndex
    cf.CFArrayGetValueAtIndex.argtypes = (CFTypeRef, CFIndex)
    cf.CFArrayGetValueAtIndex.restype = CFTypeRef
    cf.CFDictionaryGetValue.argtypes = (CFTypeRef, CFTypeRef)
    cf.CFDictionaryGetValue.restype = CFTypeRef
    cf.CFDictionaryGetCount.argtypes = (CFTypeRef,)
    cf.CFDictionaryGetCount.restype = CFIndex
    cf.CFDictionaryGetKeysAndValues.argtypes = (CFTypeRef, ctypes.POINTER(CFTypeRef), ctypes.POINTER(CFTypeRef))
    cf.CFDictionaryGetKeysAndValues.restype = None
    cf.CFNumberGetTypeID.argtypes = ()
    cf.CFNumberGetTypeID.restype = ctypes.c_ulong
    cf.CFNumberGetValue.argtypes = (CFTypeRef, ctypes.c_long, ctypes.c_void_p)
    cf.CFNumberGetValue.restype = ctypes.c_bool
    cf.CFNumberCreate.argtypes = (CFTypeRef, ctypes.c_long, ctypes.c_void_p)
    cf.CFNumberCreate.restype = CFTypeRef

    cf.CFURLCreateFromFileSystemRepresentation.argtypes = (CFTypeRef, ctypes.c_char_p, CFIndex, ctypes.c_bool)
    cf.CFURLCreateFromFileSystemRepresentation.restype = CFTypeRef

    cf.CFDictionaryCreateMutableCopy.argtypes = (CFTypeRef, CFIndex, CFTypeRef)
    cf.CFDictionaryCreateMutableCopy.restype = CFTypeRef
    cf.CFDictionarySetValue.argtypes = (CFTypeRef, CFTypeRef, CFTypeRef)
    cf.CFDictionarySetValue.restype = None

    cf.CFPropertyListCreateData.argtypes = (CFTypeRef, CFTypeRef, CFIndex, ctypes.c_ulong, ctypes.c_void_p)
    cf.CFPropertyListCreateData.restype = CFTypeRef
    cf.CFPropertyListCreateWithData.argtypes = (CFTypeRef, CFTypeRef, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)
    cf.CFPropertyListCreateWithData.restype = CFTypeRef

    # The run loop, which every listener turns: declared here once, since the
    # framework's handle is shared and a second, different declaration would
    # change the calls of the modules that made the first.
    cf.CFRunLoopGetCurrent.argtypes = ()
    cf.CFRunLoopGetCurrent.restype = CFTypeRef
    cf.CFRunLoopAddSource.argtypes = (CFTypeRef, CFTypeRef, CFTypeRef)
    cf.CFRunLoopAddSource.restype = None
    cf.CFRunLoopRemoveSource.argtypes = (CFTypeRef, CFTypeRef, CFTypeRef)
    cf.CFRunLoopRemoveSource.restype = None
    cf.CFRunLoopRunInMode.argtypes = (CFTypeRef, ctypes.c_double, ctypes.c_bool)
    cf.CFRunLoopRunInMode.restype = ctypes.c_int32
    cf.CFMachPortCreateRunLoopSource.argtypes = (CFTypeRef, CFTypeRef, CFIndex)
    cf.CFMachPortCreateRunLoopSource.restype = CFTypeRef
    cf.CFMachPortInvalidate.argtypes = (CFTypeRef,)
    cf.CFMachPortInvalidate.restype = None
    return cf


def constant(library: ctypes.CDLL, name: str) -> int:
    """Read a global ``CFTypeRef`` constant (e.g. ``kSecClass``) from a library."""
    value = CFTypeRef.in_dll(library, name).value
    if value is None:
        raise LookupError("{} is NULL".format(name))
    return value


def release(ref: Optional[int]) -> None:
    if ref:
        lib().CFRelease(ref)


def retain(ref: int) -> int:
    """``CFRetain`` a borrowed reference, making it owned; returns it. NULL is returned as is: ``CFRetain(NULL)`` aborts."""
    if ref:
        lib().CFRetain(ref)
    return ref


@contextmanager
def owned(ref: Optional[int]) -> Iterator[Optional[int]]:
    """Yield ``ref`` and ``CFRelease`` it when the block exits."""
    try:
        yield ref
    finally:
        release(ref)


def string(text: str) -> int:
    """Create a ``CFString`` (caller owns it). Embedded NUL characters are kept."""
    raw = text.encode("utf-8")
    return lib().CFStringCreateWithBytes(None, raw, len(raw), kCFStringEncodingUTF8, False)


def is_type(ref: Optional[int], type_id: int) -> bool:
    return bool(ref) and lib().CFGetTypeID(ref) == type_id


def to_str(ref: Optional[int]) -> Optional[str]:
    """Copy a ``CFString`` into a Python string (``None`` for anything else)."""
    if not is_type(ref, lib().CFStringGetTypeID()):
        return None
    cf = lib()
    size = cf.CFStringGetMaximumSizeForEncoding(cf.CFStringGetLength(ref), kCFStringEncodingUTF8) + 1
    buffer = ctypes.create_string_buffer(size)
    if not cf.CFStringGetCString(ref, buffer, size, kCFStringEncodingUTF8):
        return None
    return buffer.value.decode("utf-8")


def data(payload: bytes) -> int:
    """Create a ``CFData`` (caller owns it)."""
    return lib().CFDataCreate(None, payload, len(payload))


def to_bool(ref: Optional[int]) -> bool:
    """Read a ``CFBoolean`` (``False`` for anything else)."""
    cf = lib()
    return is_type(ref, cf.CFBooleanGetTypeID()) and bool(cf.CFBooleanGetValue(ref))


kCFNumberLongLongType = 11
kCFNumberDoubleType = 13


def number(value: float) -> int:
    """Create a ``CFNumber`` (caller owns it): an integer stays an integer."""
    if isinstance(value, int) and not isinstance(value, bool):
        integer = ctypes.c_longlong(value)
        return lib().CFNumberCreate(None, kCFNumberLongLongType, ctypes.byref(integer))
    real = ctypes.c_double(value)
    return lib().CFNumberCreate(None, kCFNumberDoubleType, ctypes.byref(real))


def file_url(path: str) -> int:
    """Create a file ``CFURL`` for ``path`` (caller owns it)."""
    raw = path.encode("utf-8")
    return lib().CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)


def to_int(ref: Optional[int]) -> Optional[int]:
    """Read a ``CFNumber`` as an integer (``None`` for anything else)."""
    cf = lib()
    if not is_type(ref, cf.CFNumberGetTypeID()):
        return None
    value = ctypes.c_longlong()
    cf.CFNumberGetValue(ref, kCFNumberLongLongType, ctypes.byref(value))
    return value.value


def items(ref: Optional[int]) -> List[int]:
    """The elements of a ``CFArray`` (borrowed references: don't release them)."""
    if not ref:
        return []
    cf = lib()
    return [cf.CFArrayGetValueAtIndex(ref, index) for index in range(cf.CFArrayGetCount(ref))]


def values(ref: Optional[int]) -> List[int]:
    """The values of a ``CFDictionary``, whatever its keys (borrowed references: don't release them)."""
    if not ref:
        return []
    cf = lib()
    count = cf.CFDictionaryGetCount(ref)
    found = (CFTypeRef * count)()
    cf.CFDictionaryGetKeysAndValues(ref, None, found)
    return [value for value in found if value]


def lookup(ref: Optional[int], key: str) -> Optional[int]:
    """The value for ``key`` in a ``CFDictionary`` (borrowed), or ``None``."""
    if not ref:
        return None
    with owned(string(key)) as name:
        return lib().CFDictionaryGetValue(ref, name)


def to_bytes(ref: Optional[int]) -> bytes:
    """Copy the contents of a ``CFData`` into Python bytes."""
    if not ref:
        return b""
    cf = lib()
    return ctypes.string_at(cf.CFDataGetBytePtr(ref), cf.CFDataGetLength(ref))


def dictionary(items: Dict[int, int]) -> int:
    """
    Create a ``CFDictionary`` from CF keys and values (caller owns it).

    Uses the standard ``kCFType`` callbacks, so the dictionary retains its keys
    and values: the caller may release its own references right after.
    """
    cf = lib()
    count = len(items)
    keys = (CFTypeRef * count)(*items.keys())
    values = (CFTypeRef * count)(*items.values())
    key_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks"))
    value_callbacks = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks"))
    return cf.CFDictionaryCreate(None, keys, values, count, key_callbacks, value_callbacks)


_BINARY_PLIST = 200  # kCFPropertyListBinaryFormat_v1_0


def to_python(ref: Optional[int]) -> Any:
    """
    Convert a property-list ``CFType`` (dictionaries, arrays, strings, numbers,
    dates, data, booleans, nested) into Python objects.

    Goes through a binary property list, so every nesting level converts at once.
    """
    if not ref:
        return None
    with owned(lib().CFPropertyListCreateData(None, ref, _BINARY_PLIST, 0, None)) as data:
        if not data:
            raise ValueError("not a property list")
        return plistlib.loads(to_bytes(data))


def from_python(value: Any) -> int:
    """The reverse of :func:`to_python`: an owned ``CFType`` for a plist-compatible Python object."""
    with owned(data(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))) as raw:
        ref = lib().CFPropertyListCreateWithData(None, raw, 0, None, None)
    if not ref:
        raise ValueError("not a property list")
    return ref


# The run loop.

_RUN_FINISHED = 1  # kCFRunLoopRunFinished: the mode has no source nor timer to wait for


def default_mode() -> int:
    """``kCFRunLoopDefaultMode``."""
    return constant(lib(), "kCFRunLoopDefaultMode")


def run_loop(seconds: float, *, once: bool = True) -> bool:
    """
    Turn this thread's run loop for up to ``seconds``; with ``once``, return after the first source handled.

    Returns ``False`` when the run loop had nothing to wait for and came back
    at once: the caller should pause instead of spinning.
    """
    return bool(lib().CFRunLoopRunInMode(default_mode(), seconds, once) != _RUN_FINISHED)


class RunLoopSource:
    """
    A run loop source added to this thread's run loop, in the default mode; :meth:`close` removes it.

    With ``owned``, the source is ours (a ``Create`` result) and :meth:`close`
    releases it too; otherwise its maker (an IOKit notification port, say)
    owns it. A NULL source raises ``MacOSError``, saying ``what`` failed.
    """

    def __init__(self, source: Optional[int], *, owned: bool, what: str) -> None:
        if not source:
            raise MacOSError("could not {}: macOS gave no run loop source".format(what))
        self.source: Optional[int] = source
        self.owned = owned
        self.loop = lib().CFRunLoopGetCurrent()
        lib().CFRunLoopAddSource(self.loop, source, default_mode())

    def close(self) -> None:
        source, self.source = self.source, None
        if source:
            lib().CFRunLoopRemoveSource(self.loop, source, default_mode())
            if self.owned:
                release(source)
