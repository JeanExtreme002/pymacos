# -*- coding: utf-8 -*-

"""
Show notifications in Notification Center.

::

    macos.notify("Build finished")
    macos.notify("3 tests failed", title="CI", subtitle="main", sound="Basso")

Notifications are posted through AppleScript's ``display notification``. The
native ``UNUserNotificationCenter`` API only works from a signed app bundle,
which a Python script isn't, so macOS attributes these notifications to
*Script Editor*. When notifications are turned off for Script Editor, macOS
drops them without any error, so :func:`notify` checks that setting and raises
:class:`~macos.errors.PermissionDeniedError` instead.
"""

import os
from typing import List, Optional

from . import defaults, sound as _sound
from ._system import require_macos, run as _run
from .errors import MacOSError, PermissionDeniedError

__all__ = ["notify", "is_allowed"]

_SCRIPT_EDITOR = "com.apple.ScriptEditor2"
_SETTINGS = "com.apple.ncprefs"  # Notification Center's preferences: its "apps" key lists each app's switches
# The "Allow notifications" switch in System Settings › Notifications. The
# settings format is undocumented; this bit is known from reverse engineering
# (e.g. the ncprefs.py project) and matches what toggling the switch changes.
_ALLOW_NOTIFICATIONS = 1 << 25
_POST_TIMEOUT = 30.0  # seconds for ``osascript`` to hand the notification over: it never waits for it to show
# Longer text is clipped: Notification Center shows a few lines at most, and a
# captured log of megabytes would overflow the arguments' limit (ARG_MAX).
_MAX_TEXT = 4096


def is_allowed() -> Optional[bool]:
    """
    Whether macOS lets Script Editor, and so :func:`macos.notify`, show notifications.

    ``None`` means it can't tell: Script Editor has never posted one yet, or
    the settings couldn't be read. Focus modes such as Do Not Disturb can still
    hide notifications that are allowed.
    """
    require_macos()
    try:
        # Through CFPreferences, in this process: a ``defaults export`` would start a process for every notification.
        # Synchronized first: a process that read them once would go on seeing its copy, not a switch turned since.
        defaults._synchronize(_SETTINGS)
        apps = defaults.read(_SETTINGS, "apps")
    except (MacOSError, ValueError, OSError):
        return None  # best effort: an unreadable format must never break notify()
    if not isinstance(apps, list):
        return None
    for app in apps:
        if isinstance(app, dict) and app.get("bundle-id") == _SCRIPT_EDITOR:
            flags = app.get("flags")
            if not isinstance(flags, int) or isinstance(flags, bool):
                return None  # missing, or a format we don't know: best effort, as above
            return bool(flags & _ALLOW_NOTIFICATIONS)
    return None


def _refuse() -> None:
    raise PermissionDeniedError(
        "macOS would silently drop this notification: notifications are turned off for Script Editor, "
        "which posts them. Turn them on in System Settings › Notifications › Script Editor."
    )


def _text(name: str, value: str) -> str:
    """``value`` as it can travel as an argument, clipped to :data:`_MAX_TEXT`."""
    if "\0" in value:
        raise ValueError("notify(): {} contains a NUL character".format(name))
    try:
        os.fsencode(value)  # as subprocess encodes it: a file name's surrogate escapes pass, a lone surrogate doesn't
    except UnicodeEncodeError:
        raise ValueError("notify(): {} contains a lone surrogate, which isn't valid text".format(name)) from None
    return value if len(value) <= _MAX_TEXT else value[: _MAX_TEXT - 1] + "\u2026"


def _sound_name(name: str) -> str:
    """The alert sound named ``name``, as :func:`macos.sound.names` spells it."""
    known = _sound.names()
    if not known:
        return name  # no sound folder could be read: best effort, let macOS look it up
    for candidate in known:
        if candidate.casefold() == name.casefold():
            return candidate
    raise ValueError("no alert sound is named {!r}; see macos.sound.names()".format(name))


def notify(
    message: str,
    *,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
    sound: Optional[str] = None,
    check_permission: bool = True,
) -> None:
    """
    Post a notification.

    ``sound`` is the name of a system alert sound, such as ``"Glass"``,
    ``"Ping"`` or ``"Basso"``: one of :func:`macos.sound.names`, in any case,
    or :class:`ValueError` is raised (macOS would post the notification
    without a sound).

    Text longer than 4096 characters is clipped, ending in "…". Text with a
    NUL character or a lone surrogate, which can't be passed to ``osascript``,
    raises :class:`ValueError`.

    Raises :class:`~macos.errors.PermissionDeniedError` when notifications are
    turned off for Script Editor, since macOS would silently drop them. Pass
    ``check_permission=False`` to skip that check (it reads the settings,
    through CFPreferences, before every notification).

    The text reaches ``osascript`` as arguments, which other processes of the
    same user can see in the process list while it runs: don't put a secret
    in a notification.
    """
    # Checked before anything is posted: a typo in a sound name would
    # otherwise be dropped without a word, and only the sound with it.
    message = _text("message", message)
    title = None if title is None else _text("title", title)
    subtitle = None if subtitle is None else _text("subtitle", subtitle)
    sound = None if sound is None else _sound_name(_text("sound", sound))
    # The text travels as script arguments (``argv``), never spliced into the
    # AppleScript source, so quotes or backslashes in it can't break or inject
    # into the script.
    values: List[str] = [message]
    statement = "display notification (item 1 of argv)"
    for clause, value in (("with title", title), ("subtitle", subtitle), ("sound name", sound)):
        if value is not None:
            values.append(value)
            statement += " {} (item {} of argv)".format(clause, len(values))

    # "--" ends osascript's options, so text starting with "-" (a message like
    # "-5 degrees", or "-e") is taken as an argument instead of a flag.
    allowed = is_allowed() if check_permission else True
    if allowed is False:
        _refuse()

    _run(["osascript", "-e", "on run argv", "-e", statement, "-e", "end run", "--", *values], timeout=_POST_TIMEOUT)

    # The first notification ever registers Script Editor with notifications
    # off, and macOS drops it without a prompt: check again now that it's known.
    if allowed is None and is_allowed() is False:
        _refuse()
