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

from typing import Optional, Sequence


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


class CommandError(MacOSError):
    """A system command the package relies on exited with an error."""

    def __init__(self, args: Sequence[str], returncode: int, stderr: str = "") -> None:
        # The constructor arguments go to Exception, so ``self.args`` can
        # rebuild the exception: that is what lets it cross a pickle, e.g.
        # from a multiprocessing worker back to the parent.
        super().__init__(list(args), returncode, stderr)
        self.cmd = list(args)
        self.returncode = returncode
        self.stderr = stderr.strip()

    def __str__(self) -> str:
        message = "{!r} exited with status {}".format(self.cmd[0], self.returncode)
        if self.stderr:
            message += ": " + self.stderr
        return message

    def __repr__(self) -> str:
        # The command's name only, as in str(): the default repr would print self.args, that is the
        # whole command line, and the arguments can hold a URL with a token, a dialog's default text,
        # a notification... which a traceback or a log line mustn't show. ``cmd`` keeps them for
        # whoever asks for them. ``stderr`` stays as the command wrote it, and may quote one.
        return "{}({!r}, returncode={!r}, stderr={!r})".format(
            type(self).__name__, self.cmd[0], self.returncode, self.stderr
        )


class CommandTimeoutError(MacOSError, TimeoutError):
    """A system command the package relies on was still running when its time ran out, and was stopped."""

    def __init__(self, args: Sequence[str], timeout: float) -> None:
        super().__init__(list(args), timeout)  # picklable, see CommandError
        self.cmd = list(args)
        self.timeout = timeout

    def __str__(self) -> str:
        return "{!r} didn't finish within {:g} seconds".format(self.cmd[0], self.timeout)

    def __repr__(self) -> str:
        # Not the arguments: see CommandError.
        return "{}({!r}, timeout={!r})".format(type(self).__name__, self.cmd[0], self.timeout)


class PromptTimeoutError(MacOSError, TimeoutError):
    """The user left a permission prompt (camera, microphone) unanswered until the time ran out."""


class WaitTimeoutError(MacOSError, TimeoutError):
    """
    What was waited for didn't happen in time.

    A copy, an appearance change, a geocoding answer, a folder walked, a Bluetooth or VPN switch, the
    Dock restarting, a default app's confirmation, a window's full-screen change.
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
