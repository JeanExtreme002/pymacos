# -*- coding: utf-8 -*-

"""
Exceptions raised by the ``macos`` package.

The errors that come from macOS derive from :class:`MacOSError`, so
``except macos.MacOSError`` catches them all. Where a builtin exception has
the same meaning, the package's exception subclasses it too, so existing
``except PermissionError`` / ``except LookupError`` handlers keep working.
Invalid arguments and missing files raise the usual builtins instead
(``ValueError``, ``FileNotFoundError``...).
"""

import signal
from typing import Iterable, List, Optional


class MacOSError(Exception):
    """Base class for the errors the ``macos`` package raises when macOS fails or refuses."""


class NotSupportedError(MacOSError):
    """The feature is not available on this system (e.g. not running on macOS)."""


class PermissionDeniedError(MacOSError, PermissionError):
    """macOS refused the operation because a privacy permission is missing."""


class MainThreadError(MacOSError, RuntimeError):
    """
    The call only works on the main thread, and was made from another.

    The camera, the menu bar, the geocoder, keyboard layouts, system events (``events.run()``) and
    documents (HTML, and conversions to PDF): see the *Threads and macOS internals* page of the docs.

    A :class:`RuntimeError` too, as :mod:`macos.menubar` raised before.
    """


class AppNotFoundError(MacOSError, LookupError):
    """No application matched the given name, bundle identifier or path."""


class AppLaunchTimeoutError(AppNotFoundError, TimeoutError):
    """
    An application was launched, but didn't show up within the time given.

    Still an :class:`AppNotFoundError`, as :func:`macos.apps.open` raised before, and a
    :class:`TimeoutError` like every other wait that ran out of time.
    """


def _name(cmd: List[str]) -> str:
    # What str() and repr() show of the command: its name, or a placeholder for an empty one, so that
    # str() never raises (a traceback would only say "<exception str() failed>").
    return cmd[0] if cmd else "<command>"


class CommandError(MacOSError):
    """A system command the package relies on exited with an error, or was killed by a signal."""

    def __init__(self, args: Iterable[str], returncode: int, stderr: str = "") -> None:
        # The constructor arguments go to Exception, so ``self.args`` can
        # rebuild the exception: that is what lets it cross a pickle, e.g.
        # from a multiprocessing worker back to the parent. One list for
        # both, or a generator would leave ``cmd`` empty.
        cmd = list(args)
        super().__init__(cmd, returncode, stderr)
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr.strip()

    def __str__(self) -> str:
        if self.returncode < 0:  # subprocess's way of saying the signal -returncode killed it: it never exited
            try:
                killer = signal.Signals(-self.returncode).name
            except ValueError:
                killer = "signal {}".format(-self.returncode)
            message = "{!r} was killed by {}".format(_name(self.cmd), killer)
        else:
            message = "{!r} exited with status {}".format(_name(self.cmd), self.returncode)
        if self.stderr:
            message += ": " + self.stderr
        return message

    def __repr__(self) -> str:
        # The command's name only, as in str(): the default repr would print self.args, that is the
        # whole command line, and the arguments can hold a URL with a token, a dialog's default text,
        # a notification... which a traceback or a log line mustn't show. ``cmd`` keeps them for
        # whoever asks for them. ``stderr`` stays as the command wrote it, and may quote one.
        return "{}({!r}, returncode={!r}, stderr={!r})".format(
            type(self).__name__, _name(self.cmd), self.returncode, self.stderr
        )


class CommandTimeoutError(MacOSError, TimeoutError):
    """A system command the package relies on was still running when its time ran out, and was stopped."""

    def __init__(self, args: Iterable[str], timeout: float) -> None:
        cmd = list(args)
        super().__init__(cmd, timeout)  # picklable, and one list: see CommandError
        # Given two arguments, OSError (which TimeoutError is) takes them for an errno and its message:
        # there's neither, as for a TimeoutError raised with a message.
        self.errno = self.strerror = None
        self.cmd = cmd
        self.timeout = timeout

    def __str__(self) -> str:
        return "{!r} didn't finish within {:g} seconds".format(_name(self.cmd), self.timeout)

    def __repr__(self) -> str:
        # Not the arguments: see CommandError.
        return "{}({!r}, timeout={!r})".format(type(self).__name__, _name(self.cmd), self.timeout)


class PromptTimeoutError(MacOSError, TimeoutError):
    """The user left a permission prompt (camera, microphone) unanswered until the time ran out."""


class WaitTimeoutError(MacOSError, TimeoutError):
    """
    What was waited for didn't happen in time.

    A copy, an appearance change, a geocoding answer, a folder walked, a Bluetooth or VPN switch, the
    Dock restarting, a default app's confirmation, a window's full-screen change, a video export, a webcam photo or video.
    """


class ShortcutNotFoundError(CommandError, LookupError):
    """No shortcut in the Shortcuts app has the given name or identifier."""


class KeychainError(MacOSError):
    """The Security framework returned an error status (``OSStatus``)."""

    def __init__(self, status: int, message: Optional[str] = None) -> None:
        super().__init__(status, message)  # picklable, see CommandError
        self.status = status
        self.message = message

    def __str__(self) -> str:
        return "{} (OSStatus {})".format(self.message or "Keychain error", self.status)
