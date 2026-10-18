# -*- coding: utf-8 -*-

"""
List the windows of running apps, and move, resize, focus, minimize and close them.

::

    for window in macos.windows.list("Safari"):
        print(window.title, window.frame)

    window = macos.windows.focused()           # the window in front
    window.move(0, 25)
    window.resize(1280, 800)
    window.minimize()

    macos.windows.tile_all()                   # every window side by side, in a grid

Uses the Accessibility API, like window managers such as Rectangle, so it
needs the *Accessibility* permission for the app running Python (your
terminal or IDE), the same one :mod:`macos.keyboard` and :mod:`macos.mouse`
need.
"""

import builtins
import ctypes
import math
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple, Union

from . import _cf, _objc, apps, defaults
from ._objc import CGPoint, CGSize
from ._system import framework, restart_process
from .errors import MacOSError, NotSupportedError, PermissionDeniedError, WaitTimeoutError

__all__ = [
    "Window",
    "LAYOUTS",
    "list",
    "wait_for",
    "focused",
    "has_permission",
    "request_permission",
    "double_click_title_bar",
    "set_double_click_title_bar",
    "tiling",
    "set_tiling",
    "click_wallpaper_to_show_desktop",
    "set_click_wallpaper_to_show_desktop",
    "animations",
    "set_animations",
    "tile",
    "tile_all",
]

_SUCCESS = 0
_FAILURE = -25200  # kAXErrorFailure: the app refused, without saying why
_API_DISABLED = -25211  # kAXErrorAPIDisabled: no Accessibility permission
_INVALID_ELEMENT = -25202  # kAXErrorInvalidUIElement: the window is gone
_CANNOT_COMPLETE = -25204  # kAXErrorCannotComplete: the app didn't answer, or quit
_ATTRIBUTE_UNSUPPORTED = -25205  # kAXErrorAttributeUnsupported: this window has no such attribute
_NO_VALUE = -25212  # kAXErrorNoValue: the attribute is there, with nothing in it
_POINT, _SIZE = 1, 2  # kAXValueCGPointType, kAXValueCGSizeType
_TIMEOUT = 2.0  # seconds to wait for an app that doesn't answer
_FULL_SCREEN_TIMEOUT = 10.0
_FULL_SCREEN_ANIMATION = 1.0
_FULL_SCREEN_RETRY = 2.0  # seconds before asking again


@lru_cache(maxsize=None)
def _accessibility() -> ctypes.CDLL:
    ax = framework("ApplicationServices")
    pointer = ctypes.c_void_p
    signatures = {
        "AXIsProcessTrusted": ((), ctypes.c_bool),
        "AXIsProcessTrustedWithOptions": ((pointer,), ctypes.c_bool),
        "AXUIElementCreateApplication": ((ctypes.c_int,), pointer),
        "AXUIElementCopyAttributeValue": ((pointer, pointer, ctypes.POINTER(pointer)), ctypes.c_int32),
        "AXUIElementSetAttributeValue": ((pointer, pointer, pointer), ctypes.c_int32),
        "AXUIElementPerformAction": ((pointer, pointer), ctypes.c_int32),
        "AXUIElementSetMessagingTimeout": ((pointer, ctypes.c_float), ctypes.c_int32),
        "AXValueCreate": ((ctypes.c_int, pointer), pointer),
        "AXValueGetValue": ((pointer, ctypes.c_int, pointer), ctypes.c_bool),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(ax, name)
        function.argtypes = argtypes
        function.restype = restype
    return ax


def has_permission() -> bool:
    """Whether this process may control other apps' windows, without prompting the user."""
    return bool(_accessibility().AXIsProcessTrusted())


def request_permission() -> bool:
    """
    Ask for the Accessibility permission, showing the system prompt; return whether it's granted.

    After the user allows the app running Python in System Settings ›
    Privacy & Security › Accessibility, that app must be restarted.
    """
    ax = _accessibility()
    key = ctypes.c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt").value
    if not key:  # a NULL key can't go in a dictionary
        raise MacOSError("could not ask for the Accessibility permission: macOS lacks its prompt option")
    options = _cf.dictionary({key: _cf.constant(_cf.lib(), "kCFBooleanTrue")})
    with _cf.owned(options):
        return bool(ax.AXIsProcessTrustedWithOptions(options))


class _AXError(MacOSError):
    """An Accessibility call failed with ``status`` (an AXError), for the callers that tell the codes apart."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


def _check(status: int, what: str) -> None:
    if status == _SUCCESS:
        return
    if status == _API_DISABLED:
        raise PermissionDeniedError(
            "Accessibility permission is missing: allow the app running Python (your terminal or IDE) in "
            "System Settings › Privacy & Security › Accessibility, then restart it"
        )
    if status == _INVALID_ELEMENT:
        raise _AXError("could not {}: the window is gone".format(what), status)
    if status == _CANNOT_COMPLETE:
        raise _AXError("could not {}: its app didn't answer (it may be busy, or have quit)".format(what), status)
    raise _AXError("could not {} (AXError {})".format(what, status), status)


def _copy(element: int, attribute: str) -> Tuple[int, Optional[int]]:
    """The status and the owned value of an attribute."""
    value = ctypes.c_void_p()
    with _cf.owned(_cf.string(attribute)) as name:
        status = _accessibility().AXUIElementCopyAttributeValue(element, name, ctypes.byref(value))
    return status, value.value if status == _SUCCESS else None


def _set(element: int, attribute: str, value: int, what: str) -> None:
    with _cf.owned(_cf.string(attribute)) as name:
        _check(_accessibility().AXUIElementSetAttributeValue(element, name, value), what)


def _app_element(pid: int) -> int:
    """An owned accessibility element for the app with ``pid``, which gives up on an app that hangs."""
    ax = _accessibility()
    element = ax.AXUIElementCreateApplication(pid)
    if not element:
        raise MacOSError("could not reach the app with pid {}".format(pid))
    ax.AXUIElementSetMessagingTimeout(element, _TIMEOUT)
    return int(element)


def _check_position(x: float, y: float) -> None:
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("x and y must be finite, not {}, {}".format(x, y))


def _check_size(width: float, height: float) -> None:
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        raise ValueError("width and height must be finite and positive, not {} x {}".format(width, height))


class Window:
    """
    A window of a running app.

    Its title, position and size are read fresh each time, so they follow the
    user moving it. Get windows with :func:`list` or :func:`focused`.
    """

    def __init__(self, element: int, app: str, pid: int) -> None:
        # ``element`` is an owned reference, released with the object.
        self._element = element
        self.app = app
        """The name of the app it belongs to, such as ``'Safari'``."""
        self.pid = pid
        """The app's process ID."""

    def __del__(self) -> None:
        element, self._element = getattr(self, "_element", 0), 0
        if element:
            _cf.release(element)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Window):
            return NotImplemented
        return bool(_cf.lib().CFEqual(self._element, other._element))

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        try:
            return "Window(app={!r}, title={!r}, frame={!r})".format(self.app, self.title, self.frame)
        except MacOSError:
            return "Window(app={!r}, closed)".format(self.app)

    def _read(self, attribute: str) -> Optional[int]:
        status, value = _copy(self._element, attribute)
        if status != _SUCCESS and status not in (_NO_VALUE, _ATTRIBUTE_UNSUPPORTED):  # treat as missing
            _check(status, "read the window's {}".format(attribute))
        return value

    def _geometry(self, attribute: str, kind: int, holder: Any) -> Any:
        value = self._read(attribute)
        if not value:
            raise MacOSError("the window has no {}".format(attribute))
        with _cf.owned(value):
            if not _accessibility().AXValueGetValue(value, kind, ctypes.byref(holder)):
                raise MacOSError("could not read the window's {}".format(attribute))
        return holder

    @property
    def title(self) -> str:
        """As shown in its title bar; ``''`` for untitled windows."""
        value = self._read("AXTitle")
        with _cf.owned(value):
            return _cf.to_str(value) or ""

    @property
    def position(self) -> Tuple[int, int]:
        """``(x, y)`` of its top-left corner, in points from the top-left of the main display."""
        point = self._geometry("AXPosition", _POINT, CGPoint())
        return (round(point.x), round(point.y))

    @property
    def size(self) -> Tuple[int, int]:
        """``(width, height)`` in points, title bar included."""
        size = self._geometry("AXSize", _SIZE, CGSize())
        return (round(size.width), round(size.height))

    @property
    def frame(self) -> Tuple[int, int, int, int]:
        """``(x, y, width, height)``, as :attr:`position` and :attr:`size`, like :func:`macos.screenshot`'s ``region``."""
        return self.position + self.size

    @property
    def minimized(self) -> bool:
        """Whether it's minimized into the Dock."""
        value = self._read("AXMinimized")
        with _cf.owned(value):
            return _cf.to_bool(value)

    @property
    def fullscreen(self) -> bool:
        """Whether it's in full screen, in a Space of its own."""
        value = self._read("AXFullScreen")
        with _cf.owned(value):
            return _cf.to_bool(value)

    def set_fullscreen(self, on: bool = True) -> None:
        """
        Enter full screen (or leave it with ``on=False``), like its green button.

        macOS animates the change into a Space of its own; this returns once
        it's done, after a second or two. Windows that can't go full screen
        raise :class:`~macos.errors.MacOSError`, and a change that doesn't
        happen within a few seconds :class:`~macos.errors.WaitTimeoutError`
        (a ``MacOSError`` too).
        """
        if self.fullscreen == bool(on):
            return  # nothing to ask, nor an animation to wait for
        what = "{} full screen".format("enter" if on else "leave")

        def request() -> None:
            try:
                self._set_flag("AXFullScreen", on, what)
            except _AXError as error:
                if on and error.status == _FAILURE:
                    raise MacOSError("this window can't go full screen: its app doesn't allow it") from None
                raise

        request()
        deadline = time.monotonic() + _FULL_SCREEN_TIMEOUT
        asked = time.monotonic()
        while self.fullscreen != bool(on):
            now = time.monotonic()
            if now > deadline:
                raise WaitTimeoutError("could not {} within {} seconds".format(what, _FULL_SCREEN_TIMEOUT))
            # macOS drops a request made while an earlier animation still runs: ask again.
            if now - asked > _FULL_SCREEN_RETRY:
                request()
                asked = now
            time.sleep(0.1)
        # The state changes as the animation starts, and macOS ignores a new
        # request until it ends: let it finish.
        time.sleep(_FULL_SCREEN_ANIMATION)

    def move(self, x: float, y: float) -> None:
        """Move its top-left corner to ``(x, y)``."""
        _check_position(x, y)
        point = CGPoint(x, y)
        value = _accessibility().AXValueCreate(_POINT, ctypes.byref(point))
        with _cf.owned(value):
            _set(self._element, "AXPosition", value, "move the window")

    def resize(self, width: float, height: float) -> None:
        """
        Resize it to ``width`` x ``height`` points.

        Apps may refuse sizes below their minimum or above the screen, and
        keep the closest size they accept.
        """
        _check_size(width, height)
        size = CGSize(width, height)
        value = _accessibility().AXValueCreate(_SIZE, ctypes.byref(size))
        with _cf.owned(value):
            _set(self._element, "AXSize", value, "resize the window")

    def set_frame(self, x: float, y: float, width: float, height: float) -> None:
        """Move and resize it at once: ``window.set_frame(0, 25, 1280, 800)``."""
        # All four checked before anything changes: a bad x mustn't leave the window resized.
        _check_size(width, height)
        _check_position(x, y)
        # Resized first: moved while still large, it could stick out of the
        # screen, and macOS would cut it to fit, over the size asked for.
        self.resize(width, height)
        self.move(x, y)
        # A window growing near the edge of the screen may have refused a size
        # that didn't fit where it was: try again now that it's in place.
        self.resize(width, height)
        self.move(x, y)

    def center(self) -> None:
        """
        Center it on the display it's on (the main one, if it's on none), keeping its size.

        Like :meth:`snap`, it centers in the area the menu bar and the Dock
        leave. A window taller than that keeps its top edge below the menu bar.
        """
        frame = self.frame
        area_x, area_y, area_width, area_height = _area_of(frame, _displays())
        _, _, width, height = frame
        left = area_x + (area_width - width) / 2
        top = max(area_y + (area_height - height) / 2, area_y)
        self.move(round(left), round(top))

    def snap(self, layout: str, *, display: Optional[int] = None) -> None:
        """
        Fit it to part of the display, like Rectangle or macOS's own tiling: ``"left"``, ``"top_right"``, ``"maximize"``...

        ::

            macos.windows.focused().snap("left")
            macos.windows.list("Terminal")[0].snap("right_third")

        The layouts are :data:`LAYOUTS`: halves (``"left"``, ``"right"``,
        ``"top"``, ``"bottom"``), quarters (``"top_left"``...), thirds
        (``"left_third"``, ``"center_third"``, ``"right_third"``,
        ``"left_two_thirds"``, ``"right_two_thirds"``) and ``"maximize"``.
        They leave out the menu bar and the Dock. The window goes to the
        display it's on, or to ``display`` (``1`` is the main one). Apps with
        a minimum size may stay larger.
        """
        if layout not in LAYOUTS:
            raise ValueError("layout must be one of {}, not {!r}".format(", ".join(LAYOUTS), layout))
        displays = _displays()
        if display is not None:
            if not 1 <= display <= len(displays):
                raise ValueError("there's no display {}: there are {}".format(display, len(displays)))
            area = displays[display - 1][1]
        else:
            area = _area_of(self.frame, displays)
        left, top, wide, tall = LAYOUTS[layout]
        area_x, area_y, area_width, area_height = area
        self.set_frame(
            round(area_x + left * area_width),
            round(area_y + top * area_height),
            round(wide * area_width),
            round(tall * area_height),
        )

    @property
    def _standard(self) -> bool:
        """Whether it's a regular document window, not a panel, a dialog or a popover."""
        value = self._read("AXSubrole")
        with _cf.owned(value):
            return _cf.to_str(value) == "AXStandardWindow"

    def _set_flag(self, attribute: str, on: bool, what: str) -> None:
        flag = _cf.constant(_cf.lib(), "kCFBooleanTrue" if on else "kCFBooleanFalse")
        _set(self._element, attribute, flag, what)

    def focus(self) -> None:
        """Bring it to the front, with its app, ready for keystrokes."""
        if self.minimized:
            self.restore()
        with _objc.autorelease_pool():
            handle = apps._handle(self.pid)  # this one app, not a scan of every process
            app = apps._app(handle) if handle else None
        if app is not None:
            try:
                # Asked, not awaited: Accessibility below makes it frontmost either way, so an app
                # LaunchServices can't switch to needn't cost the wait for it.
                app.activate(timeout=0)
            except MacOSError:
                pass  # LaunchServices can't activate some apps (helper processes): Accessibility below still can
        # macOS may refuse an activation asked by another app: make the app
        # frontmost through Accessibility too, as window managers do.
        element = _app_element(self.pid)
        try:
            true = _cf.constant(_cf.lib(), "kCFBooleanTrue")
            _set(element, "AXFrontmost", true, "bring the app to the front")
        finally:
            _cf.release(element)
        with _cf.owned(_cf.string("AXRaise")) as action:
            _check(_accessibility().AXUIElementPerformAction(self._element, action), "raise the window")
        self._set_flag("AXMain", True, "focus the window")

    def minimize(self) -> None:
        """Minimize it into the Dock."""
        self._set_flag("AXMinimized", True, "minimize the window")

    def restore(self) -> None:
        """Bring it back from the Dock."""
        self._set_flag("AXMinimized", False, "restore the window")

    def screenshot(self, path: Union[str, "os.PathLike[str]", None] = None, *, shadow: bool = False) -> Path:
        """
        Capture just this window, even when others cover it, and return the image's path.

        ``path`` works as in :func:`macos.screenshot` (a temporary PNG by
        default). ``shadow=True`` keeps the window's shadow, as ⌘⇧4 does.
        Needs the Screen Recording permission.
        """
        from . import screen

        number = ctypes.c_uint32()
        if _window_number()(self._element, ctypes.byref(number)) != 0 or not number.value:
            raise MacOSError("could not capture the window of {}: it may have closed".format(self.app))
        options = ["-l{}".format(number.value)] + ([] if shadow else ["-o"])
        return screen._capture(path, options)

    def close(self) -> None:
        """
        Close it, like its red button.

        The app may ask to save changes first, or keep running without windows.
        """
        button = self._read("AXCloseButton")
        if not button:
            raise MacOSError("the window has no close button")
        with _cf.owned(button), _cf.owned(_cf.string("AXPress")) as press:
            _check(_accessibility().AXUIElementPerformAction(button, press), "close the window")


_REGULAR, _ACCESSORY = 0, 1  # NSApplicationActivationPolicy: apps that can have windows


LAYOUTS = {
    "left": (0.0, 0.0, 0.5, 1.0),
    "right": (0.5, 0.0, 0.5, 1.0),
    "top": (0.0, 0.0, 1.0, 0.5),
    "bottom": (0.0, 0.5, 1.0, 0.5),
    "top_left": (0.0, 0.0, 0.5, 0.5),
    "top_right": (0.5, 0.0, 0.5, 0.5),
    "bottom_left": (0.0, 0.5, 0.5, 0.5),
    "bottom_right": (0.5, 0.5, 0.5, 0.5),
    "left_third": (0.0, 0.0, 1 / 3, 1.0),
    "center_third": (1 / 3, 0.0, 1 / 3, 1.0),
    "right_third": (2 / 3, 0.0, 1 / 3, 1.0),
    "left_two_thirds": (0.0, 0.0, 2 / 3, 1.0),
    "right_two_thirds": (1 / 3, 0.0, 2 / 3, 1.0),
    "maximize": (0.0, 0.0, 1.0, 1.0),
}
"""The layouts :meth:`Window.snap` takes: ``(x, y, width, height)`` as fractions of the display's usable area."""


_Rect = Tuple[float, float, float, float]


def _index_of(frame: Tuple[int, int, int, int], displays: Sequence[Tuple[_Rect, _Rect]]) -> int:
    """
    Which of ``displays`` ``frame`` is on: the one holding its middle, else the one it overlaps most, else the main (0).

    Whole displays, menu bar and Dock included: a window over a display's Dock is on that display.
    """
    x, y, width, height = frame
    middle_x, middle_y = x + width / 2, y + height / 2
    for index, ((left, top, wide, tall), _) in enumerate(displays):
        if left <= middle_x < left + wide and top <= middle_y < top + tall:
            return index
    overlaps = [
        max(0.0, min(x + width, left + wide) - max(x, left)) * max(0.0, min(y + height, top + tall) - max(y, top))
        for (left, top, wide, tall), _ in displays
    ]
    best = max(range(len(overlaps)), key=overlaps.__getitem__, default=0)
    return best if overlaps and overlaps[best] > 0 else 0  # off every display: the main one


def _area_of(frame: Tuple[int, int, int, int], displays: Sequence[Tuple[_Rect, _Rect]]) -> _Rect:
    """The usable area of the display ``frame`` is on."""
    return displays[_index_of(frame, displays)][1]


def _displays() -> "builtins.list[Tuple[_Rect, _Rect]]":
    """
    Each display's whole frame and its area without the menu bar and the Dock, main first.

    In points from the main display's top-left.
    """
    framework("AppKit")
    found = []
    with _objc.autorelease_pool():
        screens = builtins.list(_objc.nsarray(_objc.send(_objc.cls("NSScreen"), "screens")))
        if not screens:
            raise MacOSError("no display is connected")
        main_height = _objc.send(screens[0], "frame", restype=_objc.CGRect).size.height

        def flipped(rect: Any) -> _Rect:
            # AppKit measures from the main display's bottom-left corner, going up.
            top = main_height - (rect.origin.y + rect.size.height)
            return (rect.origin.x, top, rect.size.width, rect.size.height)

        for screen_ in screens:
            whole = _objc.send(screen_, "frame", restype=_objc.CGRect)
            usable = _objc.send(screen_, "visibleFrame", restype=_objc.CGRect)
            found.append((flipped(whole), flipped(usable)))
    return found


def _usable_areas() -> "builtins.list[_Rect]":
    """Each display's area without the menu bar and the Dock, main first, in points from the main display's top-left."""
    return [usable for _, usable in _displays()]


@lru_cache(maxsize=None)
def _window_number() -> Any:
    """``_AXUIElementGetWindow``: the window server's number for a window, which ``screencapture -l`` takes."""
    try:
        function = framework("ApplicationServices")._AXUIElementGetWindow
    except AttributeError:  # private: Apple may drop it in any release
        raise NotSupportedError("this version of macOS can't tell a window's number, which its screenshot needs") from None
    function.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
    function.restype = ctypes.c_int32
    return function


def _apps_with_windows() -> "builtins.list[apps.App]":
    """The regular apps and the accessory ones (menu bar apps), which can have windows too."""
    with _objc.autorelease_pool():
        return [
            apps._app(handle)
            for handle in apps._handles(True)
            if _objc.send(handle, "activationPolicy", restype=_objc.NSInteger) in (_REGULAR, _ACCESSORY)
        ]


def _windows_of(app: apps.App) -> "builtins.list[Window]":
    element = _app_element(app.pid)
    try:
        status, value = _copy(element, "AXWindows")
        if status == _API_DISABLED:
            _check(status, "list the windows")
        if not value:
            return []  # no windows, or an app that doesn't answer (busy, or still starting): see list()
        with _cf.owned(value):
            found = []
            for window in _cf.items(value):
                found.append(Window(_cf.retain(window), app.name or "", app.pid))
            return found
    finally:
        _cf.release(element)


def _targets(app: Union[str, apps.App, None]) -> "builtins.list[apps.App]":
    """The apps :func:`list` looks at for ``app``: every app that can have windows, or the one named, if it's running."""
    if app is None:
        return _apps_with_windows()
    if isinstance(app, apps.App):
        return [app]
    return _named(app)


def _named(name: str) -> "builtins.list[apps.App]":
    """Every running app :func:`macos.apps.get` would find by ``name``, not only the first: copies of one app share it."""
    running = apps.running(include_background=True)
    if apps._is_path(name):
        # Both sides go through the same mapping, as in apps.get: a translocated app's own path finds it too.
        wanted_path = apps._real_bundle_path(os.path.expanduser(name))
        return [app for app in running if app.path and apps._real_bundle_path(app.path) == wanted_path]
    wanted = name.casefold()
    found = []
    for app in running:
        file_name = os.path.basename(app.path or "")
        candidates = (app.name, app.bundle_id, file_name, os.path.splitext(file_name)[0])
        if wanted in {part.casefold() for part in candidates if part}:
            found.append(app)
    return found


def _list(targets: Sequence[apps.App], title: Optional[str]) -> "builtins.list[Window]":
    windows = [window for target in targets for window in _windows_of(target)]
    if title is None:
        return windows
    wanted = title.casefold()
    kept, busy = [], set()
    for window in windows:
        if window.pid in busy:
            continue  # its app already didn't answer: its other windows would each wait as long
        try:
            if wanted in window.title.casefold():
                kept.append(window)
        except _AXError as error:
            # Closed since it was listed, or its app went busy: as if it weren't there, like list() without a title.
            if error.status == _CANNOT_COMPLETE:
                busy.add(window.pid)
        except PermissionDeniedError:
            raise
        except MacOSError:
            continue
    return kept


def list(app: Union[str, apps.App, None] = None, *, title: Optional[str] = None) -> "builtins.list[Window]":
    """
    Return the windows of the running apps (menu bar apps included), or only of ``app``, front to back within each app.

    ``app`` is an :class:`~macos.apps.App` or an app's name (``"Safari"``);
    a name covers every running app that goes by it (several copies of one
    app, or several Python processes), an ``App`` only that one. ``title``
    keeps the windows whose title contains it, ignoring case. A window that
    closes while it's read is left out. Minimized windows are included;
    check :attr:`Window.minimized`. An app that doesn't answer within two
    seconds (busy, or still starting) counts as having no windows: ask again, or use :func:`wait_for`. So does a name
    no running app goes by (not open, or misspelt): :func:`macos.apps.get`
    tells the two apart.
    """
    if not has_permission():
        _check(_API_DISABLED, "list the windows")
    return _list(_targets(app), title)


def wait_for(
    app: Union[str, apps.App, None] = None,
    *,
    title: Optional[str] = None,
    timeout: Optional[float] = 10.0,
    interval: float = 0.25,
) -> Optional[Window]:
    """
    Wait until a window shows up, and return it; ``None`` if ``timeout`` seconds pass first.

    ``app`` and ``title`` work as in :func:`list`, which is asked again every
    ``interval`` seconds; a name no running app goes by waits out the
    ``timeout``. ``timeout=None`` waits until a window shows up. Handy after
    an action that opens a window::

        macos.keyboard.press("cmd+s")
        dialog = macos.windows.wait_for("TextEdit", title="Save")
    """
    if not interval > 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    if timeout is not None and math.isnan(timeout):
        raise ValueError("timeout must be a number of seconds or None, not nan")
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        found = list(app, title=title)
        if found:
            return found[0]
        if deadline is None:
            time.sleep(interval)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))


def focused() -> Optional[Window]:
    """
    Return the window in front (the one keystrokes go to), or ``None`` when the front app has none.

    An app that doesn't answer within two seconds (busy, or still starting) counts as having none.
    """
    if not has_permission():
        _check(_API_DISABLED, "read the focused window")
    front = apps.frontmost()
    if front is None:
        return None
    element = _app_element(front.pid)
    try:
        status, value = _copy(element, "AXFocusedWindow")
        if status == _API_DISABLED:
            _check(status, "read the focused window")
        return Window(value, front.name or "", front.pid) if value else None
    finally:
        _cf.release(element)


# --- Settings ---------------------------------------------------------------

_TITLE_BAR_ACTIONS = {"zoom": "Maximize", "fill": "Fill", "minimize": "Minimize", None: "None"}
_WINDOW_MANAGER = "com.apple.WindowManager"


def double_click_title_bar() -> Optional[str]:
    """What a double click on a window's title bar does: ``'zoom'``, ``'fill'``, ``'minimize'``, or ``None``."""
    found = defaults.read(defaults.GLOBAL, "AppleActionOnDoubleClick", default="Maximize")
    names = {value: name for name, value in _TITLE_BAR_ACTIONS.items()}
    return names.get(found, "zoom")


def set_double_click_title_bar(action: Optional[str]) -> None:
    """
    Make a double click on a title bar ``"zoom"`` the window, ``"fill"`` the screen, ``"minimize"`` it, or nothing (``None``).

    ``"fill"`` needs macOS 15 or later. Some apps pick it up only when reopened.
    """
    if action not in _TITLE_BAR_ACTIONS:
        raise ValueError("action must be 'zoom', 'fill', 'minimize' or None, not {!r}".format(action))
    defaults.write(defaults.GLOBAL, "AppleActionOnDoubleClick", _TITLE_BAR_ACTIONS[action])


def _restart_window_manager() -> None:
    """Quit the window manager, for macOS to start it again with the settings just written; once per batch."""
    restart_process("WindowManager")


def tiling() -> bool:
    """Whether dragging a window to an edge of the screen tiles it there (macOS 15 and later)."""
    return defaults._as_bool(defaults.read(_WINDOW_MANAGER, "EnableTilingByEdgeDrag", default=True), True)


def set_tiling(on: bool = True) -> None:
    """
    Tile windows dragged to an edge (to the menu bar, to fill the screen), or let them go anywhere (``False``).

    Needs macOS 15 or later; the layouts of :meth:`Window.snap` work either way.
    """
    defaults.write(_WINDOW_MANAGER, "EnableTilingByEdgeDrag", bool(on))
    defaults.write(_WINDOW_MANAGER, "EnableTopTilingByEdgeDrag", bool(on))
    _restart_window_manager()


def click_wallpaper_to_show_desktop() -> bool:
    """Whether a click on the wallpaper moves the windows away to show the desktop (macOS 14 and later)."""
    return defaults._as_bool(defaults.read(_WINDOW_MANAGER, "EnableStandardClickToShowDesktop", default=True), True)


def set_click_wallpaper_to_show_desktop(on: bool = True) -> None:
    """Make a click on the wallpaper show the desktop, or only in Stage Manager (``False``). Needs macOS 14 or later."""
    defaults.write(_WINDOW_MANAGER, "EnableStandardClickToShowDesktop", bool(on))
    _restart_window_manager()


def animations() -> bool:
    """Whether windows, sheets and panels open with an animation."""
    return defaults._as_bool(defaults.read(defaults.GLOBAL, "NSAutomaticWindowAnimationsEnabled", default=True), True)


def set_animations(on: bool = True) -> None:
    """
    Animate windows, sheets and panels as they open, or show them at once (``False``), for a snappier Mac.

    Apps pick it up when they're reopened.
    """
    defaults.write(defaults.GLOBAL, "NSAutomaticWindowAnimationsEnabled", bool(on))


# --- Tiling -----------------------------------------------------------------------


def _grid(
    count: int, area: Tuple[float, float, float, float], columns: Optional[int], gap: float
) -> "builtins.list[Tuple[int, int, int, int]]":
    """``count`` frames filling ``area`` in rows, ``gap`` points apart; the last row's windows widen to fill it."""
    if not count:
        return []
    across = min(columns or math.ceil(math.sqrt(count)), count)
    rows = math.ceil(count / across)
    # The area's edges rounded, not its origin and size: rounding both could end it a point past the real one.
    left_edge, top_edge, width, height = area
    x, y, right, bottom, space = (
        math.floor(value + 0.5) for value in (left_edge, top_edge, left_edge + width, top_edge + height, gap)
    )
    width, height = right - x, bottom - y
    if (height - space * (rows + 1)) / rows < 1 or (width - space * (across + 1)) / across < 1:
        raise ValueError("a gap of {} points leaves no room for {} windows on the display".format(gap, count))

    def edges(start: int, length: int, parts: int) -> "builtins.list[Tuple[int, int]]":
        # Whole points, each edge rounded once from an exact fraction: a window's far edge is
        # exactly the gap before the next one's near edge, so they never overlap, nor pass the end.
        room = length - space * (parts + 1)
        cut = [(2 * part * room + parts) // (2 * parts) for part in range(parts + 1)]
        return [(start + space * (part + 1) + cut[part], cut[part + 1] - cut[part]) for part in range(parts)]

    frames: "builtins.list[Tuple[int, int, int, int]]" = []
    for top, height_each in edges(y, height, rows):
        in_row = min(across, count - len(frames))
        frames.extend((left, top, width_each, height_each) for left, width_each in edges(x, width, in_row))
    return frames


def tile(
    windows: Sequence[Window], *, display: Optional[int] = None, columns: Optional[int] = None, gap: int = 0
) -> None:
    """
    Arrange ``windows`` side by side in a grid, filling the display they're on.

    ::

        macos.windows.tile(macos.windows.list("Terminal"))
        macos.windows.tile(macos.windows.list("Safari"), columns=2, gap=8)

    Each display tiles the windows on it, keeping the order they're in now
    (top to bottom, then left to right), so tiling again changes nothing; ``display`` (``1`` is the main one)
    gathers them all on one. The grid is as square as it can be, or
    ``columns`` wide, and the last row's windows widen to fill it. ``gap``
    leaves that many points between windows and around them. The menu bar
    and the Dock stay clear, and apps with a minimum size may stay larger.
    """
    _tile(windows, display, columns, gap, skip_gone=False)


def _tile(
    windows: Sequence[Window], display: Optional[int], columns: Optional[int], gap: int, *, skip_gone: bool
) -> "builtins.list[Window]":
    """:func:`tile`, returning the windows moved; ``skip_gone`` passes over those that close or stop answering."""
    if columns is not None and columns < 1:
        raise ValueError("columns must be at least 1, not {}".format(columns))
    if gap < 0:
        raise ValueError("gap can't be negative, not {}".format(gap))
    displays = _displays()
    if display is not None and not 1 <= display <= len(displays):
        raise ValueError("there's no display {}: there are {}".format(display, len(displays)))
    groups: "dict[int, builtins.list[Tuple[Tuple[int, int], Window]]]" = {}
    for window in windows:
        try:
            frame = window.frame
        except PermissionDeniedError:
            raise
        except MacOSError:
            if not skip_gone:
                raise
            continue  # closed meanwhile
        target = display - 1 if display is not None else _index_of(frame, displays)
        groups.setdefault(target, []).append(((frame[1], frame[0]), window))
    # Every frame worked out before the first window moves: a gap too large
    # for one display raises with nothing tiled, rather than half the windows.
    moves: "builtins.list[Tuple[Window, Tuple[int, int, int, int]]]" = []
    for index, members in groups.items():
        members.sort(key=lambda member: member[0])  # as they're arranged now, so tiling again keeps them in place
        moves.extend(zip((window for _, window in members), _grid(len(members), displays[index][1], columns, gap)))
    moved = []
    for window, frame in moves:
        try:
            window.set_frame(*frame)
        except PermissionDeniedError:
            raise
        except MacOSError:
            if not skip_gone:
                raise
            continue  # closed, or its app went busy, since: the others still go in place, its cell left empty
        moved.append(window)
    return moved


def tile_all(
    app: Union[str, apps.App, None] = None, *, display: Optional[int] = None, columns: Optional[int] = None, gap: int = 0
) -> "builtins.list[Window]":
    """
    Arrange every window on screen side by side, in a grid, and return the ones moved.

    ::

        macos.windows.tile_all()                    # all the apps' windows
        macos.windows.tile_all("Terminal", gap=8)   # only Terminal's

    Takes the regular windows that show: not minimized ones, full-screen
    ones, those of hidden apps, nor panels and dialogs. ``app`` keeps one
    app's, as in :func:`list`; ``display``, ``columns`` and ``gap`` work as
    in :func:`tile`. A window that closes (or whose app stops answering)
    while they're arranged is left out, and the others still go in place.
    """
    if not has_permission():
        _check(_API_DISABLED, "list the windows")
    # One scan of the processes, for the apps and their windows both: is_hidden asks LaunchServices
    # about each of these apps alone, not about every process again.
    targets = _targets(app)
    hidden = set()
    for running in targets:
        try:
            if running.is_hidden:
                hidden.add(running.pid)
        except MacOSError:
            continue  # quit meanwhile
    chosen = []
    for window in _list(targets, None):
        try:
            if window.pid not in hidden and window._standard and not window.minimized and not window.fullscreen:
                chosen.append(window)
        except MacOSError:
            continue  # closed meanwhile
    return _tile(chosen, display, columns, gap, skip_gone=True)
