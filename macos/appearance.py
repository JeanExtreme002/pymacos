# -*- coding: utf-8 -*-

"""
Read and switch the system appearance (Light / Dark mode), and read the accent color.

::

    if macos.appearance.is_dark():
        theme = "dark"
    macos.appearance.accent_color()      # '#007aff'
    macos.appearance.set_mode("dark")

The value is read fresh from the preferences daemon on every call, so it
follows the user switching modes (or *Auto* switching at sunset) while your
program runs.
"""

import ctypes
import time
from typing import Optional

from . import _cf, _objc
from ._system import applescript, framework

__all__ = [
    "is_dark",
    "mode",
    "set_mode",
    "is_auto",
    "set_auto_mode",
    "accent_color",
    "set_accent_color",
    "ACCENT_COLORS",
    "menu_bar_hidden",
    "set_hide_menu_bar",
    "wait_for_change",
    "scroll_bars",
    "set_scroll_bars",
    "font_smoothing",
    "set_font_smoothing",
]


def _read(key: str) -> Optional[int]:
    """Return an owned reference to a global-domain preference value (or ``None``)."""
    cf = _cf.lib()
    domain = _cf.constant(cf, "kCFPreferencesAnyApplication")
    cf.CFPreferencesAppSynchronize(domain)
    with _cf.owned(_cf.string(key)) as name:
        return cf.CFPreferencesCopyAppValue(name, domain)


def mode() -> str:
    """Return ``"dark"`` or ``"light"``."""
    with _cf.owned(_read("AppleInterfaceStyle")) as value:
        style = _cf.to_str(value)
    return "dark" if style == "Dark" else "light"


def is_dark() -> bool:
    """Whether Dark mode is currently in effect."""
    return mode() == "dark"


def set_mode(mode: str) -> None:
    """
    Switch the whole system to ``"dark"`` or ``"light"`` mode, like System Settings › Appearance.

    Goes through System Events, so the first time macOS asks to allow the app
    running Python (your terminal or IDE) to control it; if that's denied,
    :class:`~macos.errors.PermissionDeniedError` is raised.
    """
    if mode not in ("dark", "light"):
        raise ValueError("mode must be 'dark' or 'light', not {!r}".format(mode))
    script = 'tell application "System Events" to tell appearance preferences to set dark mode to {}'.format(
        "true" if mode == "dark" else "false"
    )
    applescript("System Events", script)  # turns -1743 into PermissionDeniedError


def is_auto() -> bool:
    """Whether the appearance is set to *Auto* (switches between Light and Dark by time of day)."""
    with _cf.owned(_read("AppleInterfaceStyleSwitchesAutomatically")) as value:
        return _cf.to_bool(value)


def accent_color() -> str:
    """
    Return the accent color chosen in System Settings › Appearance, as hex (``'#007aff'``).

    That's the color of buttons, checkboxes and selections. With *Multicolor*
    selected, it's the default blue. Handy to theme a web view, a plot or a
    terminal UI to match the Mac.
    """
    framework("AppKit")
    with _objc.autorelease_pool():
        color = _objc.send(_objc.cls("NSColor"), "controlAccentColor")
        srgb = _objc.send(_objc.cls("NSColorSpace"), "sRGBColorSpace")
        color = _objc.send(color, "colorUsingColorSpace:", srgb, argtypes=(_objc.id,))
        channels = [
            _objc.send(color, name, restype=ctypes.c_double) for name in ("redComponent", "greenComponent", "blueComponent")
        ]
    return "#" + "".join("{:02x}".format(round(min(max(value, 0.0), 1.0) * 255)) for value in channels)


def wait_for_change(*, timeout: Optional[float] = None, interval: float = 1.0) -> str:
    """
    Wait until the system switches between Light and Dark mode, and return the new mode.

    Useful to restyle a terminal UI or a plot as soon as the user (or *Auto*)
    switches. Raises :class:`TimeoutError` if nothing changes within
    ``timeout`` seconds. ``interval`` is how often to check, in seconds.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    start = mode()
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        current = mode()
        if current != start:
            return current
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("the appearance didn't change within {}s".format(timeout))
            time.sleep(min(interval, remaining))
        else:
            time.sleep(interval)


def _announce(*names: str) -> None:
    """Tell running apps a setting changed, as System Settings does, so they update at once."""
    framework("Foundation")
    with _objc.autorelease_pool():
        center = _objc.send(_objc.cls("NSDistributedNotificationCenter"), "defaultCenter")
        for name in names:
            _objc.send(
                center,
                "postNotificationName:object:userInfo:deliverImmediately:",
                _objc.nsstring(name),
                None,
                None,
                True,
                argtypes=(_objc.id, _objc.id, _objc.id, _objc.BOOL),
                restype=None,
            )


def set_auto_mode(on: bool = True) -> None:
    """
    Switch between Light and Dark by the time of day (*Auto*), or keep the current one (``False``).

    macOS may apply the switch only at the next login.
    """
    from . import defaults

    defaults.write(defaults.GLOBAL, "AppleInterfaceStyleSwitchesAutomatically", bool(on))
    _announce("AppleInterfaceThemeChangedNotification")


# AppleAccentColor's values; Multicolor is the key left unset.
_ACCENTS = {"multicolor": None, "graphite": -1, "red": 0, "orange": 1, "yellow": 2, "green": 3, "blue": 4, "purple": 5, "pink": 6}
ACCENT_COLORS = tuple(_ACCENTS)
"""The accent colors of System Settings › Appearance, for :func:`set_accent_color`."""


def set_accent_color(name: str) -> None:
    """
    Set the accent color of buttons, checkboxes and selections, like System Settings › Appearance.

    ``name`` is one of :data:`ACCENT_COLORS`: ``"blue"``, ``"purple"``,
    ``"graphite"``, ``"multicolor"`` (each app's own color)... Running apps
    update at once; a few only when reopened.
    """
    from . import defaults

    if name not in _ACCENTS:
        raise ValueError("name must be one of {}, not {!r}".format(", ".join(ACCENT_COLORS), name))
    value = _ACCENTS[name]
    if value is None:
        defaults.delete(defaults.GLOBAL, "AppleAccentColor")
    else:
        defaults.write(defaults.GLOBAL, "AppleAccentColor", value)
    _announce("AppleColorPreferencesChangedNotification", "AppleAquaColorVariantChanged")


def menu_bar_hidden() -> bool:
    """Whether the menu bar hides until the pointer reaches the top of the screen."""
    from . import defaults

    return bool(defaults.read(defaults.GLOBAL, "_HIHideMenuBar", default=False))


def set_hide_menu_bar(on: bool = True) -> None:
    """Hide the menu bar until the pointer reaches the top of the screen, like the Dock's autohide, or keep it shown."""
    from . import defaults

    defaults.write(defaults.GLOBAL, "_HIHideMenuBar", bool(on))
    _announce("AppleInterfaceMenuBarHidingChangedNotification")


_SCROLL_BARS = {"automatic": "Automatic", "when_scrolling": "WhenScrolling", "always": "Always"}


def scroll_bars() -> str:
    """When scroll bars show: ``'automatic'`` (by the mouse or trackpad), ``'when_scrolling'`` or ``'always'``."""
    from . import defaults

    found = defaults.read(defaults.GLOBAL, "AppleShowScrollBars", default="Automatic")
    names = {value: name for name, value in _SCROLL_BARS.items()}
    return names.get(found, "automatic")


def set_scroll_bars(when: str) -> None:
    """Show scroll bars ``"always"``, ``"when_scrolling"``, or ``"automatic"``-ally, like System Settings › Appearance."""
    from . import defaults

    if when not in _SCROLL_BARS:
        raise ValueError("when must be 'automatic', 'when_scrolling' or 'always', not {!r}".format(when))
    defaults.write(defaults.GLOBAL, "AppleShowScrollBars", _SCROLL_BARS[when])
    _announce("AppleShowScrollBarsSettingChanged")


def font_smoothing() -> bool:
    """Whether text is drawn a little bolder (font smoothing), as System Settings › Appearance offers."""
    from . import defaults

    return defaults.read(defaults.GLOBAL, "AppleFontSmoothing", default=1) != 0


def set_font_smoothing(on: bool = True) -> None:
    """
    Smooth fonts, or draw them thinner (``False``), which some find sharper on displays that aren't Retina.

    Apps pick it up when they're reopened.
    """
    from . import defaults

    if on:
        defaults.delete(defaults.GLOBAL, "AppleFontSmoothing")  # macOS's own
    else:
        defaults.write(defaults.GLOBAL, "AppleFontSmoothing", 0)
