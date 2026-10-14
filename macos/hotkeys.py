# -*- coding: utf-8 -*-

"""
Global keyboard shortcuts: run a function when a key combination is pressed, in any app.

::

    def screenshot():
        macos.screenshot("~/Desktop/shot.png")

    macos.hotkeys.register("ctrl+option+s", screenshot)
    macos.hotkeys.run()                       # until macos.hotkeys.stop() or Ctrl-C

    macos.hotkeys.wait("cmd+shift+k")         # or just wait for one press

Shortcuts are written as for :func:`macos.keyboard.press`. A registered
shortcut doesn't reach the app in front. Listening to the keyboard needs the
*Input Monitoring* permission for the app running Python (your terminal or
IDE), and keeping the shortcut from the app in front needs *Accessibility*.
"""

import threading
from typing import Callable, Dict, List, Optional, Tuple, Union

from . import _events, _objc, keyboard

__all__ = ["Hotkey", "register", "unregister", "run", "stop", "wait", "has_permission", "request_permission"]

_KEY_DOWN, _KEY_UP = 10, 11  # kCGEventKeyDown, kCGEventKeyUp
_KEY_CODE = 9  # kCGKeyboardEventKeycode
_AUTOREPEAT = 8  # kCGKeyboardEventAutorepeat: the key is held, repeating
_FN = 1 << 23  # kCGEventFlagMaskSecondaryFn
# The modifiers that tell shortcuts apart; Caps Lock and the keypad flag don't.
_MODIFIERS = (1 << 17) | (1 << 18) | (1 << 19) | (1 << 20) | _FN
# The keys macOS flags with Fn whether or not Fn is held: the F-keys, the
# arrows, and home, end, page up, page down, forward delete and help.
_FN_FLAGGED = frozenset(
    code
    for name, code in keyboard._KEYS.items()
    if (name.startswith("f") and name[1:].isdigit())
    or name in ("left", "right", "up", "down", "home", "end", "page_up", "page_down", "forward_delete", "help")
)

_DENIED = (
    "listening to the keyboard needs the Input Monitoring and Accessibility permissions: allow the app "
    "running Python (your terminal or IDE) in System Settings › Privacy & Security, then restart it"
)


def has_permission() -> bool:
    """
    Whether :func:`run` and :func:`wait` may listen, without prompting the user.

    They need both Input Monitoring, to listen to the keyboard, and
    Accessibility, to keep the shortcuts from the app in front: ``True`` only
    when both are granted.
    """
    return _events.has_listen_permission() and _events.has_permission()


def request_permission() -> bool:
    """
    Ask for the Input Monitoring and Accessibility permissions, showing the system prompts; return whether both are granted.

    After the user allows the app running Python in System Settings ›
    Privacy & Security › Input Monitoring and › Accessibility, that app must be restarted.
    """
    listening = _events.request_listen_permission()
    return _events.request_permission() and listening


class Hotkey:
    """A registered shortcut. :meth:`unregister` removes it."""

    def __init__(self, keys: str, code: int, flags: int, callback: Callable[[], object]) -> None:
        self.keys = keys
        """As passed to :func:`register`, such as ``'cmd+shift+k'``."""
        self.callback = callback
        self._combination = (code, flags)

    def __repr__(self) -> str:
        return "Hotkey({!r})".format(self.keys)

    def unregister(self) -> None:
        """Stop reacting to this shortcut."""
        unregister(self)


_lock = threading.Lock()
_registered: Dict[Tuple[int, int], Hotkey] = {}
# The combinations a wait() in progress listens for without a registered shortcut: how many waits
# each. Apart from _registered, so a wait() ending neither drops a shortcut register()ed meanwhile
# nor the combination another wait() for the same keys still listens for.
_waited: Dict[Tuple[int, int], int] = {}


class _Listener(_events.Listener):
    """A :func:`run` (``wanted`` is ``None``) or a :func:`wait` for the ``wanted`` combination, in progress."""

    def __init__(self, wanted: Optional[Tuple[int, int]]) -> None:
        super().__init__()
        self.wanted = wanted
        self.arrived = threading.Event()  # set when a shortcut is queued in pending

    def queue(self, combination: Tuple[int, int]) -> None:
        """Hand a pressed shortcut to this listener, from the tap's thread."""
        self.pending.append(combination)
        self.arrived.set()

    def pause(self, seconds: float) -> None:
        """Wait for the tap's thread to queue a shortcut: this thread's run loop has no tap to turn."""
        self.arrived.wait(seconds)
        self.arrived.clear()  # what came meanwhile is in pending, read on the next turn


_listeners = _events.Listeners()


def _combination(keys: str) -> Tuple[int, int]:
    """The key code and modifier flags of a shortcut such as ``"cmd+shift+k"``."""
    modifiers, code, shifted = keyboard._parse(keys)
    if code in keyboard._MODIFIER_FLAGS:
        # A modifier pressed on its own is a flags change to macOS, not a key press: the tap,
        # which listens to key presses, would never see it, and the shortcut would never fire.
        raise ValueError(
            "{!r} is a modifier on its own, which can't be a shortcut: end it with a key, such as "
            "'cmd+shift+k' or 'f5'".format(keys)
        )
    flags = 0
    for flag, _ in modifiers:
        flags |= flag
    if shifted:
        flags |= keyboard._SHIFT[0]
    return code, flags


def register(keys: str, callback: Callable[[], object]) -> Hotkey:
    """
    Call ``callback`` (with no arguments) each time ``keys`` is pressed, in any app, while :func:`run` runs.

    ``keys`` is a shortcut such as ``"ctrl+option+s"`` or ``"f5"``, written
    as for :func:`macos.keyboard.press`. Pick one apps don't use: the app in
    front won't get it. Registering a shortcut again replaces its callback.
    Holding the keys doesn't repeat the call.
    """
    code, flags = _combination(keys)
    hotkey = Hotkey(keys, code, flags, callback)
    with _lock:
        _registered[(code, flags)] = hotkey
    return hotkey


def unregister(hotkey: Union[Hotkey, str]) -> None:
    """Remove a shortcut, given the :class:`Hotkey` :func:`register` returned or its keys."""
    combination = hotkey._combination if isinstance(hotkey, Hotkey) else _combination(hotkey)
    with _lock:
        _registered.pop(combination, None)


def stop() -> None:
    """Make :func:`run` and :func:`wait` return, from a callback or from another thread; all of them, if several run."""
    _listeners.stop()


def _match(code: int, flags: int) -> Optional[Tuple[int, int]]:
    """The registered combination a key pressed with ``flags`` makes, if any."""
    flags &= _MODIFIERS
    with _lock:
        if (code, flags) in _registered or (code, flags) in _waited:
            return (code, flags)
        # macOS adds Fn to these keys by itself: "f5" is meant, unless "fn+f5" was registered.
        unflagged = (code, flags & ~_FN)
        if code in _FN_FLAGGED and flags & _FN and (unflagged in _registered or unflagged in _waited):
            return unflagged
    return None


def _dispatch(combination: Tuple[int, int], caught: _Listener) -> None:
    """
    Queue a pressed shortcut for the listeners in progress: every :func:`wait` for it, and one to call its callback.

    Only the first tap sees the keys it keeps from the apps, so the one that
    caught them shares them out: a :func:`wait` on one thread isn't robbed by
    a :func:`run` on another, and a callback isn't called twice.
    """
    active = [listener for listener in _listeners.active() if isinstance(listener, _Listener)]
    waiting = [listener for listener in active if listener.wanted == combination]
    runners = [listener for listener in active if listener.wanted is None]
    for listener in waiting:
        listener.queue(combination)
    if runners:
        runners[0].queue(combination)  # the oldest run() calls the callback
    elif not waiting:
        caught.queue(combination)  # no run(): the wait() that caught it calls it


def _handler(listener: _Listener) -> Callable[[int, int], Optional[int]]:
    """What the tap does with each key event: keep the registered shortcuts (and their key up) from the apps."""
    cg = _events.graphics()
    swallowing = set()

    def handle(kind: int, event: int) -> Optional[int]:
        if kind not in (_KEY_DOWN, _KEY_UP):
            return event
        if _events.is_ours(event):
            # Pressed by a hotkey callback: it goes to the app in front as is. Caught, a callback
            # pressing its own shortcut (to pass it on) would only call itself again, for good.
            return event
        code = int(cg.CGEventGetIntegerValueField(event, _KEY_CODE))
        if kind == _KEY_UP:
            if code in swallowing:
                swallowing.discard(code)
                return None
            return event
        combination = _match(code, int(cg.CGEventGetFlags(event)))
        if combination is None:
            return event
        if not cg.CGEventGetIntegerValueField(event, _AUTOREPEAT):
            _dispatch(combination, listener)
        swallowing.add(code)
        return None  # the app in front never sees it

    return handle


class _TapThread:
    """
    The event tap of a listener, on a thread of its own that turns its run loop, until :meth:`close`.

    The callbacks run on the listener's thread instead: while a slow one runs
    (or presses keys itself), the tap goes on passing the keyboard through.
    Were the tap on the callback's thread, every keystroke of the system would
    wait for the callback to return, until macOS switched the tap off.
    """

    def __init__(self, listener: _Listener) -> None:
        self._listener = listener
        self._done = threading.Event()
        self._ready = threading.Event()
        self._failed: List[BaseException] = []
        self._thread = threading.Thread(target=self._run, name="macos.hotkeys tap", daemon=True)
        self._thread.start()
        try:
            self._ready.wait()
        except BaseException:  # Ctrl-C while the tap starts: stop it too, or it would swallow the shortcuts for good
            self.close()
            raise
        if self._failed:
            self._thread.join()
            raise self._failed[0]

    def _run(self) -> None:
        listener = self._listener
        try:
            tap = _events.Tap([_KEY_DOWN, _KEY_UP], _handler(listener), listener, listen_only=False, denied=_DENIED)
        except BaseException as error:  # no tap (no permission...): the listener's thread raises it
            self._failed.append(error)
            self._ready.set()
            return
        self._ready.set()
        try:
            while not self._done.is_set() and not listener.stop.is_set():
                _objc.spin(_events._SLICE)
        except BaseException as error:
            listener.errors.append(error)
        finally:
            tap.close()

    def close(self) -> None:
        self._done.set()
        self._thread.join()


def _listen(on_press: Callable[[Tuple[int, int]], bool], wanted: Optional[Tuple[int, int]], timeout: Optional[float]) -> None:
    """
    Listen for shortcuts until ``stop()``, the timeout, or ``on_press`` returning ``True``.

    ``on_press`` gets the pressed combinations that match a shortcut, on this
    thread; the tap runs on its own (see :class:`_TapThread`), so a slow
    ``on_press`` doesn't hold up the keyboard.
    """
    listener = _Listener(wanted)
    with _listeners.listening(listener):
        tapping = _TapThread(listener)
        try:
            for combination in listener.drain(timeout):
                if on_press(combination):
                    return
        finally:
            tapping.close()


def _call(combination: Tuple[int, int]) -> None:
    with _lock:
        hotkey = _registered.get(combination)
    if hotkey is not None:
        with _events.marked():  # the keys it presses aren't shortcuts to catch: see _handler
            hotkey.callback()


def run(*, timeout: Optional[float] = None) -> None:
    """
    Listen for the registered shortcuts and call their callbacks, until :func:`stop` or ``timeout`` seconds.

    Callbacks run on this thread, one at a time; an exception in one stops
    :func:`run` and propagates. Ctrl-C stops it too. The keyboard is watched
    from another thread meanwhile, so a slow callback doesn't hold up the
    keys typed in other apps, and may press keys itself.
    """

    def call(combination: Tuple[int, int]) -> bool:
        _call(combination)
        return False

    _listen(call, None, timeout)


def wait(keys: str, *, timeout: Optional[float] = None) -> bool:
    """
    Wait until ``keys`` is pressed, in any app; return ``False`` if ``timeout`` seconds pass first.

    Handy to start or pause a script from anywhere::

        print("Press Ctrl-Option-S to start")
        macos.hotkeys.wait("ctrl+option+s")
    """
    combination = _combination(keys)
    with _lock:
        _waited[combination] = _waited.get(combination, 0) + 1
    pressed: List[bool] = []

    def check(hit: Tuple[int, int]) -> bool:
        if hit == combination:
            pressed.append(True)
            return True
        _call(hit)  # another shortcut, and no run() to serve it: still serve it
        return False

    try:
        _listen(check, combination, timeout)
    finally:
        with _lock:
            _waited[combination] -= 1
            if not _waited[combination]:
                del _waited[combination]
    return bool(pressed)
