# -*- coding: utf-8 -*-

"""
Internal helpers for :mod:`macos.keyboard` and :mod:`macos.mouse`: posting
Quartz events and the Accessibility permission they need, and listening to
the user's input.
"""

import collections
import ctypes
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Callable, Iterator, List, Optional

from . import _cf, _objc
from ._objc import CGPoint
from ._system import framework
from .errors import PermissionDeniedError

HID_TAP = 0  # kCGHIDEventTap: as if the events came from the hardware
PAUSE = 0.005  # between events, so apps see them in order

# The modifier flags of the keys held down by macos.keyboard.hold(), one entry
# per key: every event posted meanwhile carries them, so a click becomes a
# Shift-click. Per thread: a key held on one thread must not reach the clicks
# and keystrokes another one posts at the same time.
_held = threading.local()


def held() -> List[int]:
    """The flags of the keys :func:`macos.keyboard.hold` holds down on this thread (a list hold() changes)."""
    flags: Optional[List[int]] = getattr(_held, "flags", None)
    if flags is None:
        flags = _held.flags = []
    return flags


def held_flags() -> int:
    flags = 0
    for flag in held():
        flags |= flag
    return flags


_TapCallback = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p)
# CGDisplayReconfigurationCallBack, for macos.events: declared with the rest of CoreGraphics.
DisplayCallback = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p)


@lru_cache(maxsize=None)
def graphics() -> ctypes.CDLL:
    cg = framework("CoreGraphics")
    pointer = ctypes.c_void_p
    signatures = {
        "CGPreflightPostEventAccess": ((), ctypes.c_bool),
        "CGRequestPostEventAccess": ((), ctypes.c_bool),
        "CGEventCreate": ((pointer,), pointer),
        "CGEventGetLocation": ((pointer,), CGPoint),
        "CGEventCreateKeyboardEvent": ((pointer, ctypes.c_uint16, ctypes.c_bool), pointer),
        "CGEventKeyboardSetUnicodeString": ((pointer, ctypes.c_ulong, ctypes.POINTER(ctypes.c_uint16)), None),
        "CGEventCreateMouseEvent": ((pointer, ctypes.c_uint32, CGPoint, ctypes.c_uint32), pointer),
        "CGEventCreateScrollWheelEvent2": (
            (pointer, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32),
            pointer,
        ),
        "CGEventSetFlags": ((pointer, ctypes.c_uint64), None),
        "CGEventSetIntegerValueField": ((pointer, ctypes.c_uint32, ctypes.c_int64), None),
        "CGEventPost": ((ctypes.c_uint32, pointer), None),
        "CGEventSourceFlagsState": ((ctypes.c_int32,), ctypes.c_uint64),
        "CGEventGetIntegerValueField": ((pointer, ctypes.c_uint32), ctypes.c_int64),
        "CGEventGetFlags": ((pointer,), ctypes.c_uint64),
        "CGEventKeyboardGetUnicodeString": (
            (pointer, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_uint16)),
            None,
        ),
        "CGEventTapCreate": (
            (ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64, _TapCallback, pointer),
            pointer,
        ),
        "CGEventTapEnable": ((pointer, ctypes.c_bool), None),
        "CGPreflightListenEventAccess": ((), ctypes.c_bool),
        "CGRequestListenEventAccess": ((), ctypes.c_bool),
        "CGDisplayRegisterReconfigurationCallback": ((DisplayCallback, pointer), ctypes.c_int32),
        "CGDisplayRemoveReconfigurationCallback": ((DisplayCallback, pointer), ctypes.c_int32),
        # Through this handle, not CoreFoundation's: its own function object, declared once here.
        "CFRelease": ((pointer,), None),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(cg, name)
        function.argtypes = argtypes
        function.restype = restype
    return cg


def has_permission() -> bool:
    """Whether this process may send keystrokes and mouse events, without prompting the user."""
    return bool(graphics().CGPreflightPostEventAccess())


def request_permission() -> bool:
    """
    Ask for the Accessibility permission, which sending keystrokes and mouse events needs; return whether it's granted.

    macOS asks only once: after that, the user must allow the app running
    Python (your terminal or IDE) in System Settings › Privacy & Security ›
    Accessibility, and restart it.
    """
    return bool(graphics().CGRequestPostEventAccess())


def require_permission() -> None:
    # Without the permission macOS doesn't fail: it silently drops the events.
    if not has_permission():
        raise PermissionDeniedError(
            "Accessibility permission is missing: allow the app running Python (your terminal or IDE) in "
            "System Settings › Privacy & Security › Accessibility, then restart it"
        )


def post(event: int) -> None:
    """Post an owned event, then release it."""
    cg = graphics()
    try:
        cg.CGEventPost(HID_TAP, event)
    finally:
        cg.CFRelease(event)
    time.sleep(PAUSE)


_SESSION_TAP = 1  # kCGSessionEventTap
_HEAD, _TAIL = 0, 1  # kCGHeadInsertEventTap, kCGTailAppendEventTap
_DEFAULT, _LISTEN_ONLY = 0, 1  # kCGEventTapOptionDefault, kCGEventTapOptionListenOnly
_TAP_DISABLED = (0xFFFFFFFE, 0xFFFFFFFF)  # by timeout, by user input: turn the tap back on
_SLICE = 0.1  # seconds the run loop turns before a listener checks for stop() and its deadline


class Listener:
    """
    What one listening call (``run()``, ``wait()``, ``watch()``) gathers: its own queue, stop flag and errors.

    Callbacks from macOS append to :attr:`pending` and never raise: an
    exception must not cross back into C, so they keep it in :attr:`errors`,
    and :meth:`drain` raises it on the Python side.
    """

    def __init__(self) -> None:
        self.pending: "collections.deque[Any]" = collections.deque()
        self.stop = threading.Event()
        self.errors: List[BaseException] = []

    def check(self) -> None:
        """Raise the first exception a callback kept, if any."""
        if self.errors:
            raise self.errors.pop(0)

    def drain(self, timeout: Optional[float]) -> Iterator[Any]:
        """
        Turn this thread's run loop, and yield what the callbacks queue, until :attr:`stop` or ``timeout`` seconds.

        Each turn has its own autorelease pool, so what the callbacks
        autorelease doesn't pile up over a long run.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            self.check()
            while self.pending and not self.stop.is_set():
                if deadline is not None and time.monotonic() >= deadline:
                    # Out of time: what was queued by now still comes (it happened within the wait),
                    # but nothing queued later, so a steady stream can't keep it going for good.
                    for _ in range(len(self.pending)):
                        if self.stop.is_set():
                            return
                        yield self.pending.popleft()
                    return
                yield self.pending.popleft()
            if self.stop.is_set():
                return
            remaining = _SLICE if deadline is None else min(_SLICE, deadline - time.monotonic())
            if remaining <= 0:
                return
            self.pause(remaining)

    def pause(self, seconds: float) -> None:
        """Wait up to ``seconds`` for the callbacks, between two looks at :attr:`pending`: by turning this thread's run loop."""
        _objc.spin(seconds)


class Listeners:
    """The listening calls in progress of a module, so its ``stop()`` reaches all of them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: List[Listener] = []

    @contextmanager
    def listening(self, listener: Listener) -> Iterator[Listener]:
        """Count ``listener`` in while the block runs: a ``stop()`` from its very start on is kept."""
        with self._lock:
            self._active.append(listener)
        try:
            yield listener
        finally:
            with self._lock:
                self._active.remove(listener)

    def active(self) -> List[Listener]:
        with self._lock:
            return list(self._active)

    def stop(self) -> None:
        for listener in self.active():
            listener.stop.set()


class Tap:
    """
    A Quartz event tap for ``kinds`` (CGEventType values), on this thread's run loop until :meth:`close`.

    ``handle(kind, event)`` runs inside the tap, so it must be quick; it
    returns the event to pass on, or ``None`` to keep it from the apps (not
    with ``listen_only``, where the events go on unchanged whatever it
    returns). An exception it raises goes to ``listener``, to be raised by
    its :meth:`Listener.drain`, and the event goes on: no keystroke is lost
    to a bug. A tap macOS switches off (a slow consumer) is switched back on.
    ``denied`` is the error when macOS refuses the tap.
    """

    def __init__(
        self,
        kinds: List[int],
        handle: Callable[[int, int], Optional[int]],
        listener: Listener,
        *,
        listen_only: bool,
        denied: str,
    ) -> None:
        self._handle = handle
        self._listener = listener
        self.port: Optional[int] = None
        self.source: Optional[_cf.RunLoopSource] = None
        self.callback = _TapCallback(self._tap)  # kept alive for as long as the tap runs
        mask = 0
        for kind in kinds:
            mask |= 1 << kind
        place, option = (_TAIL, _LISTEN_ONLY) if listen_only else (_HEAD, _DEFAULT)
        port = graphics().CGEventTapCreate(_SESSION_TAP, place, option, mask, self.callback, None)
        if not port:
            raise PermissionDeniedError(denied)
        self.port = port
        try:
            self.source = _cf.RunLoopSource(
                _cf.lib().CFMachPortCreateRunLoopSource(None, port, 0), owned=True, what="listen to the input events"
            )
        except BaseException:
            self.close()
            raise

    def _tap(self, proxy: int, kind: int, event: int, refcon: int) -> Optional[int]:
        if kind in _TAP_DISABLED:  # macOS switched the tap off: switch it back on
            if self.port:
                graphics().CGEventTapEnable(self.port, True)
            return event
        try:
            return self._handle(kind, event)
        except Exception as error:  # an exception must not cross back into the window server
            self._listener.errors.append(error)
            return event

    def close(self) -> None:
        if self.source is not None:
            self.source.close()
            self.source = None
        port, self.port = self.port, None
        if port:
            _cf.lib().CFMachPortInvalidate(port)
            _cf.release(port)


def listen(kinds: List[int], convert: Callable[[int, int], Any], timeout: Optional[float], denied: str) -> Iterator[Any]:
    """
    Yield ``convert(kind, event)`` for each input event of ``kinds`` (CGEventType values), as it happens.

    A listen-only tap on this thread's run loop: the events go on to the apps
    unchanged. ``convert`` runs inside the tap, so it must be quick; returning
    ``None`` skips the event, and an exception it raises comes out of the
    iteration. Stops after ``timeout`` seconds, or when the caller stops
    iterating. ``denied`` is the error when macOS refuses the tap.
    """
    listener = Listener()

    def handle(kind: int, event: int) -> int:
        item = convert(kind, event)
        if item is not None:
            listener.pending.append(item)
        return event

    tap = Tap(kinds, handle, listener, listen_only=True, denied=denied)
    try:
        yield from listener.drain(timeout)
    finally:
        tap.close()
