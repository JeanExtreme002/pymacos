# -*- coding: utf-8 -*-

"""
Read the pointer position, move it, click, drag and scroll.

::

    macos.mouse.position()               # (512.0, 384.0)
    macos.mouse.move(100, 200)
    macos.mouse.click()                  # where the pointer is
    macos.mouse.click(300, 400, button="right")
    macos.mouse.scroll(5)                # 5 lines down
    macos.mouse.click_text("Submit")     # wherever it shows on the screen

    for click in macos.mouse.watch():    # every click, in any app
        print(click.x, click.y, click.button)

    with macos.keyboard.hold("shift"):   # Shift-click
        macos.mouse.click(300, 400)

Positions are in points from the top-left corner of the main display, like
:func:`macos.screenshot`'s ``region`` and :class:`macos.screen.Display`.

Reading the position needs no permission. Moving, clicking and scrolling need
the *Accessibility* permission for the app running Python (your terminal or
IDE); without it macOS silently drops the events, so these functions raise
:class:`~macos.errors.PermissionDeniedError` instead.
"""

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Optional, Sequence, Tuple

from . import _events
from ._objc import CGPoint
from .errors import MacOSError

if TYPE_CHECKING:
    from .screen import TextMatch

__all__ = [
    "position",
    "move",
    "click",
    "click_text",
    "drag",
    "scroll",
    "Click",
    "watch",
    "tracking_speed",
    "set_tracking_speed",
    "has_permission",
    "request_permission",
    "scroll_speed",
    "set_scroll_speed",
    "double_click_speed",
    "set_double_click_speed",
    "acceleration",
    "set_acceleration",
]

has_permission = _events.has_permission
request_permission = _events.request_permission

# CGEventType values and CGMouseButton numbers, per button.
_BUTTONS = {
    #          down, up, dragged, button
    "left": (1, 2, 6, 0),
    "right": (3, 4, 7, 1),
    "middle": (25, 26, 27, 2),
}
_MOVED = 5  # kCGEventMouseMoved
_CLICK_STATE = 1  # kCGMouseEventClickState: 2 for the second click of a double-click
_LINES = 1  # kCGScrollEventUnitLine


def position() -> Tuple[float, float]:
    """Where the pointer is, as ``(x, y)`` in points from the top-left corner of the main display."""
    cg = _events.graphics()
    event = cg.CGEventCreate(None)
    if not event:
        raise MacOSError("could not read the pointer position")
    try:
        point = cg.CGEventGetLocation(event)
    finally:
        cg.CFRelease(event)
    return (round(point.x, 1), round(point.y, 1))


def _button(button: str) -> Tuple[int, int, int, int]:
    if button not in _BUTTONS:
        raise ValueError("button must be 'left', 'right' or 'middle', not {!r}".format(button))
    return _BUTTONS[button]


def _mouse_event(kind: int, x: float, y: float, button: int, clicks: int = 0) -> int:
    cg = _events.graphics()
    event = cg.CGEventCreateMouseEvent(None, kind, CGPoint(x, y), button)
    if not event:
        raise MacOSError("could not create a mouse event")
    if clicks:
        cg.CGEventSetIntegerValueField(event, _CLICK_STATE, clicks)
    flags = _events.held_flags()
    if flags:  # inside macos.keyboard.hold(), on this thread
        cg.CGEventSetFlags(event, flags)
    return event


def _glide(kind: int, x: float, y: float, button: int, duration: float) -> None:
    """Move to ``(x, y)`` in steps over ``duration`` seconds (or at once), posting ``kind`` events."""
    start_x, start_y = position()
    steps = max(1, int(duration * 60))  # about 60 moves a second, like a real mouse
    for step in range(1, steps + 1):
        fraction = step / steps
        _events.post(_mouse_event(kind, start_x + (x - start_x) * fraction, start_y + (y - start_y) * fraction, button))
        if steps > 1:
            time.sleep(duration / steps)


def move(x: float, y: float, *, duration: float = 0.0) -> None:
    """
    Move the pointer to ``(x, y)``, at once or gliding over ``duration`` seconds.

    Apps see it as a real mouse movement (hover effects, tooltips). Needs the
    Accessibility permission.
    """
    if duration < 0:
        raise ValueError("duration must not be negative, not {}".format(duration))
    _events.require_permission()
    _glide(_MOVED, x, y, 0, duration)


def click(x: Optional[float] = None, y: Optional[float] = None, *, button: str = "left", count: int = 1) -> None:
    """
    Click at ``(x, y)``, or where the pointer is.

    ``button`` is ``"left"``, ``"right"`` or ``"middle"``; ``count=2`` is a
    double-click. Needs the Accessibility permission.
    """
    down, up, _, number = _button(button)
    if count < 1:
        raise ValueError("count must be at least 1, not {}".format(count))
    if (x is None) != (y is None):
        raise ValueError("pass both x and y, or neither")
    _events.require_permission()
    if x is not None and y is not None:
        _glide(_MOVED, x, y, 0, 0.0)
    else:
        x, y = position()
    for clicks in range(1, count + 1):
        _events.post(_mouse_event(down, x, y, number, clicks))
        _events.post(_mouse_event(up, x, y, number, clicks))


def click_text(
    text: str,
    *,
    timeout: Optional[float] = None,
    button: str = "left",
    count: int = 1,
    region: Optional[Tuple[int, int, int, int]] = None,
    display: Optional[int] = None,
    languages: Optional[Sequence[str]] = None,
) -> "TextMatch":
    """
    Click the middle of ``text`` where it shows on the screen, and return the :class:`~macos.screen.TextMatch`.

    ::

        macos.mouse.click_text("Accept")
        macos.mouse.click_text("Download", timeout=30)   # wait for it to show up first

    Text is found as :func:`macos.screen.find_text` does, ignoring case; the
    first match from the top is clicked. With ``timeout``, it waits up to that
    many seconds for the text to show up. Raises
    :class:`~macos.errors.MacOSError` when it isn't on the screen. Needs the
    Screen Recording and Accessibility permissions.
    """
    from . import screen

    if timeout is None:
        found = screen.find_text(text, region=region, display=display, languages=languages)
        match = found[0] if found else None
    else:
        match = screen.wait_for_text(text, timeout=timeout, region=region, display=display, languages=languages)
    if match is None:
        raise MacOSError("{!r} isn't on the screen".format(text))
    click(*match.center, button=button, count=count)
    return match


def drag(x: float, y: float, *, button: str = "left", duration: float = 0.3) -> None:
    """
    Press ``button`` where the pointer is, move to ``(x, y)`` over ``duration`` seconds, and release it.

    Moves windows, selects text, drops files... Use :func:`move` first to
    choose where the drag starts. Needs the Accessibility permission.
    """
    down, up, dragged, number = _button(button)
    if duration < 0:
        raise ValueError("duration must not be negative, not {}".format(duration))
    _events.require_permission()
    start_x, start_y = position()
    _events.post(_mouse_event(down, start_x, start_y, number, 1))
    try:
        _glide(dragged, x, y, number, duration)
    finally:
        # Always let go, or the button stays pressed for the whole system.
        _events.post(_mouse_event(up, x, y, number, 1))


def scroll(lines: int, *, horizontal: bool = False) -> None:
    """
    Scroll by ``lines``: positive scrolls down (towards the end), negative up.

    With ``horizontal=True``, positive scrolls right and negative left. It
    scrolls what is under the pointer. Needs the Accessibility permission.
    """
    if not lines:
        return
    _events.require_permission()
    # A wheel turned "up" is positive for Core Graphics: flip the sign.
    vertical, sideways = (0, -lines) if horizontal else (-lines, 0)
    event = _events.graphics().CGEventCreateScrollWheelEvent2(None, _LINES, 2, vertical, sideways, 0)
    if not event:
        raise MacOSError("could not create a scroll event")
    _events.post(event)


@dataclass(frozen=True)
class Click:
    """A mouse click, as :func:`watch` sees it."""

    x: float
    y: float
    """Where, in points from the main display's top-left corner, like :func:`click` takes."""
    button: str
    """``'left'``, ``'right'`` or ``'middle'`` (``'button4'`` and up for extra buttons)."""
    count: int
    """1 for a single click, 2 for the second click of a double-click, and so on."""


_BUTTON_NUMBER = 3  # kCGMouseEventButtonNumber


def watch(*, timeout: Optional[float] = None) -> Iterator[Click]:
    """
    Yield a :class:`Click` each time a mouse button goes down, in any app, as it happens.

    ::

        for click in macos.mouse.watch():
            print("clicked at", click.x, click.y)

    It only listens: the clicks still reach the apps. It goes on until you
    ``break`` out of the loop, or ``timeout`` seconds pass.
    """
    cg = _events.graphics()
    downs = {_BUTTONS["left"][0]: "left", _BUTTONS["right"][0]: "right", _BUTTONS["middle"][0]: None}

    def convert(kind: int, event: int) -> Click:
        where = cg.CGEventGetLocation(event)
        button = downs[kind]
        if button is None:  # the other buttons: 2 is the middle one
            number = int(cg.CGEventGetIntegerValueField(event, _BUTTON_NUMBER))
            button = "middle" if number == 2 else "button{}".format(number + 1)
        return Click(where.x, where.y, button, int(cg.CGEventGetIntegerValueField(event, _CLICK_STATE)))

    return _events.listen(
        list(downs),
        convert,
        timeout,
        "listening to the mouse needs the Input Monitoring permission: allow the app running Python (your "
        "terminal or IDE) in System Settings › Privacy & Security › Input Monitoring, then restart it",
    )


_SPEED_MAX = 3.0  # the slider's range in System Settings goes up to 3


def tracking_speed() -> float:
    """The pointer speed with a mouse, from 0.0 (slowest) to 1.0 (fastest). For the trackpad, see :mod:`macos.trackpad`."""
    from . import defaults

    return round(float(defaults.read(defaults.GLOBAL, "com.apple.mouse.scaling", default=1.0)) / _SPEED_MAX, 3)


def set_tracking_speed(speed: float) -> None:
    """
    Set the pointer speed with a mouse, from 0.0 to 1.0, like the slider in System Settings.

    Takes effect at the next login.
    """
    from . import defaults
    from ._system import apply_input_settings

    if not 0.0 <= speed <= 1.0:
        raise ValueError("speed must be from 0.0 to 1.0, not {}".format(speed))
    defaults.write(defaults.GLOBAL, "com.apple.mouse.scaling", round(speed * _SPEED_MAX, 3))
    apply_input_settings()


_SCROLL_DEFAULT = 0.3125  # com.apple.scrollwheel.scaling when it isn't set


def scroll_speed() -> float:
    """How fast a mouse's wheel scrolls, as macOS keeps it: 0.3125 by default, higher is faster."""
    from . import defaults

    return float(defaults.read(defaults.GLOBAL, "com.apple.scrollwheel.scaling", default=_SCROLL_DEFAULT))


def set_scroll_speed(speed: float) -> None:
    """
    Set how fast a mouse's wheel scrolls: ``0`` is the slowest, 0.3125 the default, and higher is faster.

    Takes effect at the next login.
    """
    from . import defaults
    from ._system import apply_input_settings

    if speed < 0:
        raise ValueError("speed must not be negative, not {}".format(speed))
    defaults.write(defaults.GLOBAL, "com.apple.scrollwheel.scaling", float(speed))
    apply_input_settings()


def double_click_speed() -> float:
    """The most seconds between two clicks that still make a double click (0.5 by default)."""
    from . import defaults

    return float(defaults.read(defaults.GLOBAL, "com.apple.mouse.doubleClickThreshold", default=0.5))


def set_double_click_speed(seconds: float) -> None:
    """
    Make two clicks up to ``seconds`` apart a double click, for the mouse and the trackpad.

    Shorter asks for quicker clicks. Apps pick it up when they're reopened.
    """
    from . import defaults

    if seconds <= 0:
        raise ValueError("seconds must be positive, not {}".format(seconds))
    defaults.write(defaults.GLOBAL, "com.apple.mouse.doubleClickThreshold", float(seconds))


def acceleration() -> bool:
    """Whether the pointer goes farther the faster the mouse moves (pointer acceleration, on by default)."""
    from . import defaults

    return not defaults.read(defaults.GLOBAL, "com.apple.mouse.linear", default=False)


def set_acceleration(on: bool = True) -> None:
    """
    Turn pointer acceleration on, or off (``False``): then the pointer moves in proportion to the mouse, as gamers like.

    Like *Pointer acceleration* in System Settings › Mouse › Advanced
    (macOS 14 and later). Applies at once, and stays after a restart.
    """
    import json

    from . import defaults
    from ._system import run as _run

    defaults.write(defaults.GLOBAL, "com.apple.mouse.linear", not on)
    # The saved setting is read at login: tell the mouse driver now too.
    _run(["hidutil", "property", "--set", json.dumps({"HIDUseLinearScalingMouseAcceleration": 0 if on else 1})])
