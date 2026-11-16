"""
A tiny app with one window, for the window tests: python _window_app.py TITLE SECONDS [controls].

With ``controls``, the window holds a checkbox, a text field and a button, for the tests of :mod:`macos.ui`.
"""

import ctypes
import sys
import time

from macos import _objc
from macos._system import framework


def _add_controls(window: int) -> None:
    content = _objc.send(window, "contentView")

    def place(view: int, x: float, y: float, width: float, height: float) -> None:
        frame = _objc.CGRect(_objc.CGPoint(x, y), _objc.CGSize(width, height))
        _objc.send(view, "setFrame:", frame, argtypes=(_objc.CGRect,), restype=None)
        _objc.send(content, "addSubview:", view, argtypes=(_objc.id,), restype=None)

    checkbox = _objc.send(_objc.send(_objc.cls("NSButton"), "alloc"), "init")
    _objc.send(checkbox, "setButtonType:", 3, argtypes=(_objc.NSUInteger,), restype=None)  # NSButtonTypeSwitch
    _objc.send(checkbox, "setTitle:", _objc.nsstring("Remember me"), argtypes=(_objc.id,), restype=None)
    place(checkbox, 20, 140, 200, 24)

    field = _objc.send(_objc.send(_objc.cls("NSTextField"), "alloc"), "init")
    _objc.send(field, "setPlaceholderString:", _objc.nsstring("Your name"), argtypes=(_objc.id,), restype=None)
    place(field, 20, 100, 200, 24)

    button = _objc.send(_objc.send(_objc.cls("NSButton"), "alloc"), "init")
    _objc.send(button, "setBezelStyle:", 1, argtypes=(_objc.NSUInteger,), restype=None)  # rounded: a push button
    _objc.send(button, "setTitle:", _objc.nsstring("Push"), argtypes=(_objc.id,), restype=None)
    place(button, 20, 50, 100, 32)


def main(title: str, seconds: float, controls: bool = False) -> None:
    framework("AppKit")
    with _objc.autorelease_pool():
        app = _objc.send(_objc.cls("NSApplication"), "sharedApplication")
        _objc.send(app, "setActivationPolicy:", 1, argtypes=(_objc.NSInteger,), restype=_objc.BOOL)  # accessory: no Dock icon
        _objc.send(app, "finishLaunching", restype=None)
        frame = _objc.CGRect(_objc.CGPoint(40, 40), _objc.CGSize(320, 200))
        style = 1 | 2 | 4 | 8  # titled, closable, miniaturizable, resizable
        window = _objc.send(_objc.cls("NSWindow"), "alloc")
        window = _objc.send(
            window,
            "initWithContentRect:styleMask:backing:defer:",
            frame,
            style,
            2,
            False,
            argtypes=(_objc.CGRect, _objc.NSUInteger, _objc.NSUInteger, _objc.BOOL),
        )
        _objc.send(window, "setReleasedWhenClosed:", False, argtypes=(_objc.BOOL,), restype=None)
        # Allow full screen, as regular app windows do (NSWindowCollectionBehaviorFullScreenPrimary).
        _objc.send(window, "setCollectionBehavior:", 1 << 7, argtypes=(_objc.NSUInteger,), restype=None)
        _objc.send(window, "setTitle:", _objc.nsstring(title), argtypes=(_objc.id,), restype=None)
        if controls:
            _add_controls(window)
        _objc.send(window, "makeKeyAndOrderFront:", None, argtypes=(_objc.id,), restype=None)
        print("ready", flush=True)
        mode = _objc.nsstring("kCFRunLoopDefaultMode")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            with _objc.autorelease_pool():
                until = _objc.send(_objc.cls("NSDate"), "dateWithTimeIntervalSinceNow:", 0.05, argtypes=(ctypes.c_double,))
                event = _objc.send(
                    app,
                    "nextEventMatchingMask:untilDate:inMode:dequeue:",
                    ctypes.c_uint64(0xFFFFFFFFFFFFFFFF),
                    until,
                    mode,
                    True,
                    argtypes=(ctypes.c_uint64, _objc.id, _objc.id, _objc.BOOL),
                )
                if event:
                    _objc.send(app, "sendEvent:", event, argtypes=(_objc.id,), restype=None)
            if not _objc.send(window, "isVisible", restype=_objc.BOOL) and not _objc.send(
                window, "isMiniaturized", restype=_objc.BOOL
            ):
                break  # closed


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), controls=sys.argv[3:] == ["controls"])
