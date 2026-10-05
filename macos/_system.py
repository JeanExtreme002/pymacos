# -*- coding: utf-8 -*-

"""
Internal helpers shared by every module: the platform guard, running system
commands and loading system frameworks.
"""

import ctypes
import subprocess
import sys
import warnings
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Callable, Dict, Iterator, Optional, Sequence, TypeVar

from .errors import CommandError, CommandTimeoutError, NotSupportedError, PermissionDeniedError


def require_macos() -> None:
    """Raise :class:`NotSupportedError` unless running on macOS."""
    if sys.platform != "darwin":
        raise NotSupportedError("pymacos only works on macOS (running on {!r})".format(sys.platform))


_F = TypeVar("_F", bound=Callable[..., Any])


def deprecated(replacement: str, *, removal: str) -> Callable[[_F], _F]:
    """
    Mark a public function as deprecated: calling it warns, then runs it as before.

    ``replacement`` names what to use instead (``"macos.volume.set"``) and
    ``removal`` the version it goes away in. The policy, in CONTRIBUTING.md:
    a name is deprecated for at least one minor release before it's removed,
    and only removed in a major one.
    """
    import functools

    def decorate(function: _F) -> _F:
        message = "{}.{}() is deprecated and will be removed in pymacos {}; use {} instead".format(
            function.__module__, function.__name__, removal, replacement
        )

        @functools.wraps(function)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(message, DeprecationWarning, stacklevel=2)  # points at the caller's line
            return function(*args, **kwargs)

        wrapper.__doc__ = "Deprecated: use :func:`{}` instead.\n\n{}".format(replacement, function.__doc__ or "")
        return wrapper  # type: ignore[return-value]

    return decorate


def run(args: Sequence[str], *, input: Optional[str] = None, timeout: Optional[float] = None) -> str:
    """
    Run a system command and return its standard output.

    Arguments are passed as a list (never through a shell), so user-provided
    text can't be interpreted as shell syntax. A non-zero exit status raises
    :class:`CommandError` carrying the command's stderr. With ``timeout``,
    a command still running after that many seconds is killed, and
    :class:`CommandTimeoutError` raised.
    """
    require_macos()

    try:
        result = subprocess.run(
            list(args), input=input, capture_output=True, text=True, encoding="utf-8", timeout=timeout
        )
    except FileNotFoundError:
        raise NotSupportedError("the {!r} command was not found on this system".format(args[0])) from None
    except subprocess.TimeoutExpired:
        raise CommandTimeoutError(args, timeout or 0) from None

    if result.returncode != 0:
        raise CommandError(args, result.returncode, result.stderr)
    return result.stdout


def applescript(app: str, script: str, *args: str, input: Optional[str] = None) -> str:
    """
    Run an AppleScript that controls ``app``, and return its output.

    ``args`` reach the script's ``on run argv`` handler as text, never
    pasted into the source, even when they start with ``-``. ``input`` goes
    to its standard input instead, for text that shouldn't show in the
    process list. A missing Automation permission raises
    :class:`PermissionDeniedError`, saying where to allow it.
    """
    try:
        return run(["osascript", "-e", script, *(["--", *args] if args else [])], input=input)
    except CommandError as error:
        if "-1743" in error.stderr:  # errAEEventNotPermitted
            raise PermissionDeniedError(
                "Automation permission is missing: allow the app running Python (your terminal or IDE) to control "
                "{} in System Settings › Privacy & Security › Automation".format(app)
            ) from None
        raise


_ACTIVATE_SETTINGS = "/System/Library/PrivateFrameworks/SystemAdministration.framework/Resources/activateSettings"


def apply_input_settings() -> None:
    """
    Make the keyboard, mouse and trackpad settings just written take effect, as System Settings does.

    Some (key repeat, pointer speed) still wait for the next login.
    """
    import os

    if restart_later("input settings", apply_input_settings):
        return
    if os.path.exists(_ACTIVATE_SETTINGS):
        try:
            run([_ACTIVATE_SETTINGS, "-u"])
        except CommandError:
            pass  # the settings are saved anyway; they apply at the next login


@lru_cache(maxsize=None)
def framework(name: str) -> ctypes.CDLL:
    """Load a system framework (e.g. ``"AppKit"``) once and cache the handle."""
    require_macos()
    return ctypes.CDLL("/System/Library/Frameworks/{0}.framework/{0}".format(name))


@lru_cache(maxsize=None)
def private_framework(name: str) -> ctypes.CDLL:
    """
    Load one of Apple's private frameworks, raising :class:`NotSupportedError` when this macOS lacks it.

    Private frameworks (brightness, keyboard backlight...) have no public
    alternative, but Apple may change them in any release: callers check
    what they need exists before using it.
    """
    require_macos()
    try:
        return ctypes.CDLL("/System/Library/PrivateFrameworks/{0}.framework/{0}".format(name))
    except OSError:
        raise NotSupportedError("this version of macOS doesn't have {}".format(name)) from None


# Restarts (the Dock, Finder...) put off until a batch of changes ends, by name.
_deferred: Optional[Dict[str, Callable[[], None]]] = None


def restart_later(name: str, restart: Callable[[], None]) -> bool:
    """Inside :func:`batched_restarts`, note ``restart`` to run once at its end and return ``True``; else ``False``."""
    if _deferred is None:
        return False
    _deferred[name] = restart
    return True


@contextmanager
def batched_restarts() -> Iterator[None]:
    """Run each restart asked for in the block once, when it ends (even if it fails), instead of after every change."""
    global _deferred
    if _deferred is not None:
        yield  # already batching
        return
    _deferred = {}
    try:
        yield
    finally:
        pending, _deferred = _deferred, None
        for restart in pending.values():
            restart()
