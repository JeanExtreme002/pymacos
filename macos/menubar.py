# -*- coding: utf-8 -*-

"""
Menu bar icons: put an icon or a short text in the menu bar, with a menu of actions.

::

    timer = macos.menubar.Item("☕")

    @timer.action("Start")
    def start():
        timer.set_title("25:00")

    timer.add("Reset", lambda: timer.set_title("☕"))
    macos.menubar.run()                       # until Quit, macos.menubar.quit() or Ctrl-C

:func:`run` keeps the script running and the icons responsive. Menu actions
and :func:`every` timers run on that thread, one at a time; titles and menu
items may be changed from any thread. Icons need no permission and don't put
Python in the Dock.
"""

import ctypes
import os
import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, List, Optional, Union, cast

from . import _objc
from ._objc import BOOL, NSInteger
from ._system import framework, require_macos

__all__ = ["Item", "MenuItem", "Timer", "run", "quit", "every"]

Image = Union[bytes, str, "os.PathLike[str]"]

_ACCESSORY = 1  # NSApplicationActivationPolicyAccessory: no Dock icon, no menu bar of its own
_VARIABLE_LENGTH = -1.0  # NSVariableStatusItemLength: as wide as the title or icon
_ANY_EVENT = 0xFFFFFFFFFFFFFFFF  # NSEventMaskAny
_ICON_SIZE = 18.0  # points: the height of the icons macOS draws in the menu bar
_SLICE = 0.1  # seconds the event loop waits before checking timers, calls and quit()

_Clicked = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

_lock = threading.Lock()
_running: List[threading.Event] = []  # the quit flag of each run() in progress: quit() sets them all
_clicks: Deque[int] = deque()  # tags of the menu items clicked, run by run() after the click
_calls: Deque[Callable[[], None]] = deque()  # changes made from other threads, done on the main one
_actions: Dict[int, "MenuItem"] = {}
_items: List["Item"] = []
_timers: List["Timer"] = []
_next_tag = [1]


def _clicked(target: int, _cmd: int, sender: int) -> None:
    # Called by AppKit inside sendEvent: queue the action, so an exception in it
    # reaches run() instead of being swallowed by the ctypes callback.
    _clicks.append(int(_objc.send(sender, "tag", restype=NSInteger)))


def _on_main(change: Callable[[], None]) -> None:
    """Do an AppKit change now on the main thread, or queue it for :func:`run` from any other."""
    if threading.current_thread() is threading.main_thread():
        change()
    else:
        _calls.append(change)


def _require_main_thread(what: str) -> None:
    require_macos()
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("{} must run on the main thread, as AppKit requires".format(what))


_app: List[int] = []
_target: List[int] = []


def _application() -> int:
    """The shared ``NSApplication``, set up once as an accessory app (no Dock icon)."""
    if not _app:
        framework("AppKit")
        app = _objc.send(_objc.cls("NSApplication"), "sharedApplication")
        _objc.send(app, "setActivationPolicy:", _ACCESSORY, argtypes=(NSInteger,), restype=BOOL)
        _objc.send(app, "finishLaunching", restype=None)
        _objc.define_class("PymacosMenuTarget", {"pymacosClicked:": ("v@:@", _Clicked, _clicked)})
        _target.append(_objc.send(_objc.new("PymacosMenuTarget"), "retain"))
        _app.append(app)
    return _app[0]


def _image(icon: Image, template: bool) -> int:
    """A retained ``NSImage`` sized for the menu bar, from a file path or the bytes of an image."""
    if isinstance(icon, (bytes, bytearray)):
        image = _objc.send(
            _objc.send(_objc.cls("NSImage"), "alloc"), "initWithData:", _objc.nsdata(bytes(icon)), argtypes=(_objc.id,)
        )
        label = "the icon bytes"
    else:
        path = os.path.abspath(os.path.expanduser(os.fspath(icon)))
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        image = _objc.send(
            _objc.send(_objc.cls("NSImage"), "alloc"), "initWithContentsOfFile:", _objc.nsstring(path), argtypes=(_objc.id,)
        )
        label = path
    if not image:
        raise ValueError("{} is not an image macOS can read".format(label))
    size = _objc.send(image, "size", restype=_objc.CGSize)
    # Keep the proportions, at the menu bar's height.
    scale = _ICON_SIZE / size.height if size.height else 1.0
    _objc.send(image, "setSize:", _objc.CGSize(size.width * scale, _ICON_SIZE), argtypes=(_objc.CGSize,), restype=None)
    _objc.send(image, "setTemplate:", bool(template), argtypes=(BOOL,), restype=None)
    return int(image)


class MenuItem:
    """An entry of an :class:`Item`'s menu, as :meth:`Item.add` returns it; its ``set_*`` methods update it."""

    def __init__(
        self, native: int, tag: int, title: str, callback: Optional[Callable[[], object]], enabled: bool, checked: bool
    ) -> None:
        self._native: Optional[int] = native  # None once its item is removed: changes then do nothing
        self._tag = tag
        self._title = title
        self._enabled = enabled
        self._checked = checked
        self.callback = callback
        """Called with no arguments when the entry is clicked; ``None`` for none."""

    def __repr__(self) -> str:
        return "MenuItem({!r})".format(self._title)

    def _update(self, selector: str, value: object, argtype: object) -> None:
        def apply() -> None:
            if self._native is not None:  # checked when applied: a removal may be queued before
                _objc.send(self._native, selector, value, argtypes=(argtype,), restype=None)

        _on_main(apply)

    @property
    def title(self) -> str:
        """The text of the entry."""
        return self._title

    def set_title(self, value: str) -> None:
        """Change the text of the entry."""
        self._title = str(value)
        text = self._title

        def apply() -> None:
            if self._native is not None:
                _objc.send(self._native, "setTitle:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)

        _on_main(apply)

    @property
    def enabled(self) -> bool:
        """Whether the entry can be clicked; a disabled one is greyed out."""
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """Let the entry be clicked, or grey it out with ``False``."""
        self._enabled = bool(value)
        self._update("setEnabled:", self._enabled, BOOL)

    @property
    def checked(self) -> bool:
        """Whether the entry shows a checkmark, for an option that's on or off."""
        return self._checked

    def set_checked(self, value: bool) -> None:
        """Show a checkmark next to the entry, or hide it with ``False``."""
        self._checked = bool(value)
        self._update("setState:", int(self._checked), NSInteger)


class Item:
    """
    An icon or a short text in the menu bar, with a menu. It shows as soon as it's created.

    ``title`` is the text shown, ``icon`` an image (a file path or its bytes),
    or both. An icon is drawn as a ``template`` by default: in the menu bar's
    color, in light and dark mode alike, so a black PNG with transparency works
    best; pass ``template=False`` to keep its colors. ``tooltip`` shows when the
    pointer rests on it. The menu ends with a *Quit* entry that makes :func:`run`
    return; ``quit=None`` leaves it out, and any other text renames it.

    Create it on the main thread, before :func:`run`.
    """

    def __init__(
        self,
        title: Optional[str] = None,
        *,
        icon: Optional[Image] = None,
        template: bool = True,
        tooltip: Optional[str] = None,
        quit: Optional[str] = "Quit",
    ) -> None:
        if title is None and icon is None:
            raise ValueError("a menu bar item needs a title, an icon, or both")
        _require_main_thread("creating a menu bar item")
        _application()
        # Load the icon first: a bad one must fail before anything is in the menu bar.
        image = _image(icon, template) if icon is not None else None
        bar = _objc.send(_objc.cls("NSStatusBar"), "systemStatusBar")
        native = _objc.send(bar, "statusItemWithLength:", _VARIABLE_LENGTH, argtypes=(ctypes.c_double,))
        self._native = int(_objc.send(native, "retain"))
        self._button = int(_objc.send(self._native, "button"))
        self._menu = int(_objc.send(_objc.send(_objc.cls("NSMenu"), "alloc"), "init"))
        # Our enabled flags decide, not AppKit's guess from the action's target.
        _objc.send(self._menu, "setAutoenablesItems:", False, argtypes=(BOOL,), restype=None)
        _objc.send(self._native, "setMenu:", self._menu, argtypes=(_objc.id,), restype=None)
        self._entries: List[MenuItem] = []
        self._quit_entry: Optional[MenuItem] = None
        self._quit_line: Optional[int] = None  # the separator above Quit: add() inserts before it
        self._removing = False  # set by remove() at once, under _lock: no more entries after it
        self._removed = False  # set once the native objects are released, on the main thread
        self._title: Optional[str] = None
        self._tooltip: Optional[str] = None
        self.set_title(title)
        if image is not None:
            self._show_icon(image)
        if tooltip is not None:
            self.set_tooltip(tooltip)
        if quit is not None:
            line = int(_objc.send(_objc.cls("NSMenuItem"), "separatorItem"))
            self._quit_entry = _native_entry(str(quit), _quit_all, None, True, False)
            for native in (line, self._quit_entry._native):
                _objc.send(self._menu, "addItem:", native, argtypes=(_objc.id,), restype=None)
            self._quit_line = line
        with _lock:
            _items.append(self)

    def __repr__(self) -> str:
        return "Item({!r})".format(self._title)

    @property
    def title(self) -> Optional[str]:
        """The text shown in the menu bar; ``None`` shows only the icon."""
        return self._title

    def set_title(self, value: Optional[str]) -> None:
        """Change the text shown in the menu bar; ``None`` shows only the icon."""
        self._title = None if value is None else str(value)
        text = self._title or ""

        def apply() -> None:
            if not self._removed:
                _objc.send(self._button, "setTitle:", _objc.nsstring(text), argtypes=(_objc.id,), restype=None)

        _on_main(apply)

    @property
    def tooltip(self) -> Optional[str]:
        """The text shown when the pointer rests on the item."""
        return self._tooltip

    def set_tooltip(self, value: Optional[str]) -> None:
        """Change the text shown when the pointer rests on the item, or remove it with ``None``."""
        self._tooltip = None if value is None else str(value)
        text = self._tooltip

        def show() -> None:
            if self._removed:
                return
            native = _objc.nsstring(text) if text is not None else None
            _objc.send(self._button, "setToolTip:", native, argtypes=(_objc.id,), restype=None)

        _on_main(show)

    def set_icon(self, icon: Optional[Image], *, template: bool = True) -> None:
        """Show ``icon`` (a file path or the bytes of an image), or remove it with ``None``."""
        self._show_icon(_image(icon, template) if icon is not None else None)

    def _show_icon(self, image: Optional[int]) -> None:
        """Put ``image`` (retained, or ``None``) on the button, and drop our reference to it."""

        def show() -> None:
            if not self._removed:
                _objc.send(self._button, "setImage:", image, argtypes=(_objc.id,), restype=None)
            if image:
                _objc.send(image, "release", restype=None)  # the button keeps its own reference

        _on_main(show)

    @property
    def entries(self) -> List[MenuItem]:
        """The entries added with :meth:`add` and :meth:`action`, in order."""
        return list(self._entries)

    def _insert(self, native: int) -> None:
        """Put a native menu item at the end of the user's entries: above the Quit section, if any."""
        if self._quit_line is None:
            _objc.send(self._menu, "addItem:", native, argtypes=(_objc.id,), restype=None)
            return
        at = _objc.send(self._menu, "indexOfItem:", self._quit_line, argtypes=(_objc.id,), restype=NSInteger)
        _objc.send(self._menu, "insertItem:atIndex:", native, at, argtypes=(_objc.id, NSInteger), restype=None)

    def add(
        self,
        title: str,
        callback: Optional[Callable[[], object]] = None,
        *,
        key: Optional[str] = None,
        enabled: bool = True,
        checked: bool = False,
    ) -> MenuItem:
        """
        Add an entry to the menu, above *Quit*, and return it.

        ``callback`` is called with no arguments when it's clicked. ``key`` is a
        letter that clicks it with ⌘ while the menu is open (an uppercase one
        with ⌘⇧). A ``checked`` entry
        shows a checkmark; flip it with :meth:`MenuItem.set_checked` in its
        callback for a setting that turns on and off.
        """
        _require_main_thread("adding a menu entry")
        self._require_present("adding a menu entry")
        entry = _native_entry(str(title), callback, key, enabled, checked)
        self._insert(cast(int, entry._native))  # just made: set until remove()
        self._entries.append(entry)
        return entry

    def action(
        self, title: str, *, key: Optional[str] = None, enabled: bool = True, checked: bool = False
    ) -> Callable[[Callable[[], object]], Callable[[], object]]:
        """
        A decorator that adds the function as a menu entry, like :meth:`add`::

            @item.action("Refresh", key="r")
            def refresh():
                ...
        """

        def decorate(function: Callable[[], object]) -> Callable[[], object]:
            self.add(title, function, key=key, enabled=enabled, checked=checked)
            return function

        return decorate

    def separator(self) -> None:
        """Add a line between entries, above *Quit*."""
        _require_main_thread("adding a menu separator")
        self._require_present("adding a menu separator")
        self._insert(_objc.send(_objc.cls("NSMenuItem"), "separatorItem"))

    def _require_present(self, what: str) -> None:
        with _lock:
            if self._removing:
                raise RuntimeError("{} to a menu bar item that was removed".format(what))

    def remove(self) -> None:
        """
        Take the item out of the menu bar for good.

        Its entries stop calling back, and changing them does nothing; adding
        entries raises :class:`RuntimeError`. It may be called from any thread.
        """
        with _lock:
            if self._removing:
                return
            self._removing = True
            if self in _items:
                _items.remove(self)

        def take_out() -> None:
            # On the main thread, like add(): the entries are all known here.
            self._removed = True
            entries = self._entries + ([self._quit_entry] if self._quit_entry else [])
            with _lock:
                for entry in entries:
                    _actions.pop(entry._tag, None)
            bar = _objc.send(_objc.cls("NSStatusBar"), "systemStatusBar")
            _objc.send(bar, "removeStatusItem:", self._native, argtypes=(_objc.id,), restype=None)
            for entry in entries:
                if entry._native is not None:
                    _objc.send(entry._native, "release", restype=None)  # ours; the menu drops its own
                    entry._native = None
            for native in (self._menu, self._native):
                _objc.send(native, "release", restype=None)

        _on_main(take_out)


def _native_entry(
    title: str, callback: Optional[Callable[[], object]], key: Optional[str], enabled: bool, checked: bool
) -> MenuItem:
    """A new ``NSMenuItem`` (retained, not yet in a menu) whose clicks call ``callback`` through :func:`run`."""
    native = _objc.send(
        _objc.send(_objc.cls("NSMenuItem"), "alloc"),
        "initWithTitle:action:keyEquivalent:",
        _objc.nsstring(title),
        _objc.sel("pymacosClicked:"),
        _objc.nsstring(key or ""),
        argtypes=(_objc.id, ctypes.c_void_p, _objc.id),
    )
    with _lock:
        tag = _next_tag[0]
        _next_tag[0] += 1
    _objc.send(native, "setTarget:", _target[0], argtypes=(_objc.id,), restype=None)
    _objc.send(native, "setTag:", tag, argtypes=(NSInteger,), restype=None)
    _objc.send(native, "setEnabled:", bool(enabled), argtypes=(BOOL,), restype=None)
    _objc.send(native, "setState:", int(bool(checked)), argtypes=(NSInteger,), restype=None)
    entry = MenuItem(int(native), tag, title, callback, enabled, checked)
    with _lock:
        _actions[tag] = entry
    return entry


class Timer:
    """A repeating call made by :func:`every`; :meth:`cancel` stops it."""

    def __init__(self, seconds: float, callback: Callable[[], object]) -> None:
        self.seconds = seconds
        self.callback = callback
        self._next = time.monotonic() + seconds
        self._cancelled = False

    def __repr__(self) -> str:
        return "Timer({}s, {!r})".format(self.seconds, self.callback)

    def cancel(self) -> None:
        """Stop calling it."""
        self._cancelled = True
        with _lock:
            if self in _timers:
                _timers.remove(self)


def every(seconds: float, callback: Callable[[], object]) -> Timer:
    """
    Call ``callback`` (with no arguments) every ``seconds`` while :func:`run` runs, the first time after ``seconds``.

    Handy to keep a title current, such as a countdown or the battery level.
    Calls pause while a menu is open.
    """
    if seconds <= 0:
        raise ValueError("seconds must be positive, not {}".format(seconds))
    timer = Timer(float(seconds), callback)
    with _lock:
        _timers.append(timer)
    return timer


def _quit_all() -> None:
    with _lock:
        for flag in _running:
            flag.set()


def quit() -> None:
    """Make :func:`run` return, from a menu action, a timer or another thread."""
    _quit_all()


def _due_timers(now: float) -> List[Timer]:
    with _lock:
        due = [timer for timer in _timers if not timer._cancelled and timer._next <= now]
    for timer in due:
        # Skip the ticks missed while busy, rather than catching up in a burst:
        # the next one is always a full interval after a late call.
        following = timer._next + timer.seconds
        timer._next = following if following > now else now + timer.seconds
    return due


def _pump(app: int, wait: float) -> None:
    """Deliver the events of the next ``wait`` seconds (clicks on the icons), then run what they queued."""
    with _objc.autorelease_pool():
        until = _objc.send(_objc.cls("NSDate"), "dateWithTimeIntervalSinceNow:", wait, argtypes=(ctypes.c_double,))
        event = _objc.send(
            app,
            "nextEventMatchingMask:untilDate:inMode:dequeue:",
            _ANY_EVENT,
            until,
            _objc.nsstring("kCFRunLoopDefaultMode"),
            True,
            argtypes=(ctypes.c_uint64, _objc.id, _objc.id, BOOL),
        )
        if event:
            _objc.send(app, "sendEvent:", event, argtypes=(_objc.id,), restype=None)
    # Their own pool: a timer that updates a title every second would
    # otherwise leave its strings behind for as long as the script runs.
    with _objc.autorelease_pool():
        while _calls:
            _calls.popleft()()
        while _clicks:
            with _lock:
                entry = _actions.get(_clicks.popleft())
            if entry is not None and entry.callback is not None:
                entry.callback()
        for timer in _due_timers(time.monotonic()):
            timer.callback()


def run(*, timeout: Optional[float] = None) -> None:
    """
    Keep the menu bar items responsive and call their actions, until *Quit*, :func:`quit` or ``timeout`` seconds.

    Run it on the main thread, after creating the items. Menu actions and
    :func:`every` timers run here, one at a time; an exception in one stops
    :func:`run` and propagates. Ctrl-C stops it too. The items stay in the
    menu bar after it returns, until :meth:`Item.remove` or the script ends.
    """
    _require_main_thread("macos.menubar.run()")
    # Its own flag, counted in before anything else: a quit() from now on is
    # kept, and an old one, made while nothing ran, doesn't stop this run.
    stopped = threading.Event()
    with _lock:
        _running.append(stopped)
    try:
        app = _application()
        deadline = None if timeout is None else time.monotonic() + timeout
        while not stopped.is_set():
            wait = _SLICE if deadline is None else min(_SLICE, deadline - time.monotonic())
            if wait <= 0:
                break
            _pump(app, wait)
    finally:
        with _lock:
            _running.remove(stopped)
