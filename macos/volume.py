# -*- coding: utf-8 -*-

"""
Read and change the output volume.

::

    macos.volume.get()        # 50
    macos.volume.set(30)
    macos.volume.mute()
    macos.volume.is_muted()   # True
    macos.volume.unmute()

Uses AppleScript's volume settings (part of Standard Additions), which need no
permission. They act on the current output device, like the volume keys.
"""

from typing import Optional

from ._system import run as _run

__all__ = ["get", "set", "mute", "unmute", "is_muted"]

_TIMEOUT = 30.0  # seconds: the volume settings answer at once, unless the audio daemon is wedged


def _setting(name: str) -> Optional[str]:
    # "missing value" when the output device has no volume control (e.g. some
    # HDMI and USB audio devices).
    value = _run(["osascript", "-e", "{} of (get volume settings)".format(name)], timeout=_TIMEOUT).strip()
    return None if value == "missing value" else value


def get() -> Optional[int]:
    """Return the output volume, from 0 to 100, or ``None`` if the output device has no volume control."""
    value = _setting("output volume")
    return int(value) if value is not None else None


def set(level: int) -> None:
    """Set the output volume, from 0 (silent) to 100. It doesn't change whether it's muted."""
    if isinstance(level, bool) or not isinstance(level, int):
        raise TypeError("the volume must be an int from 0 to 100, not {!r}".format(level))
    if not 0 <= level <= 100:
        raise ValueError("the volume must be from 0 to 100, not {}".format(level))
    _run(["osascript", "-e", "set volume output volume {}".format(level)], timeout=_TIMEOUT)


def mute() -> None:
    """Mute the output, keeping the volume level for when it's unmuted."""
    _run(["osascript", "-e", "set volume output muted true"], timeout=_TIMEOUT)


def unmute() -> None:
    """Unmute the output."""
    _run(["osascript", "-e", "set volume output muted false"], timeout=_TIMEOUT)


def is_muted() -> Optional[bool]:
    """Whether the output is muted, or ``None`` if the output device has no volume control."""
    value = _setting("output muted")
    return value == "true" if value is not None else None
