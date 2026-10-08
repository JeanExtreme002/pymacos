# -*- coding: utf-8 -*-

"""
Internal helpers shared by every module: the platform guard, running system
commands and loading system frameworks.
"""

import ctypes
import signal
import subprocess
import sys
import threading
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


def run(
    args: Sequence[str],
    *,
    input: Optional[str] = None,
    timeout: Optional[float] = None,
    exact_newlines: bool = False,
) -> str:
    """
    Run a system command and return its standard output.

    Arguments are passed as a list (never through a shell), so user-provided
    text can't be interpreted as shell syntax. A non-zero exit status raises
    :class:`CommandError` carrying the command's stderr. With ``timeout``,
    a command still running after that many seconds is killed, and
    :class:`CommandTimeoutError` raised.

    Text mode turns ``\r\n`` and ``\r`` into ``\n``; ``exact_newlines=True``
    keeps them as the command wrote them, for output that holds file names
    (which may contain any of them).

    Output that isn't valid UTF-8 never raises: in text mode the bad bytes
    become U+FFFD, and with ``exact_newlines=True`` they are kept the way
    :func:`os.fsdecode` keeps them (surrogate escapes), so a file name read
    back still opens the same file.
    """
    require_macos()

    if exact_newlines:
        options: Dict[str, Any] = {"input": None if input is None else input.encode("utf-8")}
    else:
        options = {"input": input, "text": True, "encoding": "utf-8", "errors": "replace"}
    try:
        result = subprocess.run(list(args), capture_output=True, timeout=timeout, **options)
    except FileNotFoundError:
        raise NotSupportedError("the {!r} command was not found on this system".format(args[0])) from None
    except subprocess.TimeoutExpired:
        raise CommandTimeoutError(args, timeout or 0) from None

    stdout, stderr = result.stdout, result.stderr
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "surrogateescape")
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    if result.returncode != 0:
        raise CommandError(args, result.returncode, stderr)
    return stdout


class UnfinishedInterrupt(KeyboardInterrupt):
    """Ctrl-C, after which the command didn't finish in its grace time and was killed: what it wrote is incomplete."""


def run_to_the_end(args: Sequence[str], *, timeout: float, grace: float) -> None:
    """
    Run a command that saves its work when told to stop (``screencapture -v``), letting it finish on Ctrl-C.

    ``subprocess.run`` kills the command a quarter of a second after Ctrl-C,
    which cuts a movie being written short. Here it runs in a session of its
    own, so a terminal's Ctrl-C reaches Python only; Python then asks it to
    stop, once (SIGINT), and gives it ``grace`` seconds to finish its file
    before ``KeyboardInterrupt`` goes on. When it doesn't finish in time, it is
    killed and :class:`UnfinishedInterrupt` (a ``KeyboardInterrupt``) says its
    file is incomplete. Otherwise it is as :func:`run`, minus the output.
    """
    require_macos()
    try:
        process = subprocess.Popen(
            list(args), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True
        )
    except FileNotFoundError:
        raise NotSupportedError("the {!r} command was not found on this system".format(args[0])) from None
    try:
        _, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        raise CommandTimeoutError(args, timeout) from None
    except KeyboardInterrupt as interrupt:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)  # the only one it gets: it's in a session of its own
        try:
            process.communicate(timeout=grace)
        except BaseException:  # out of time, or a second Ctrl-C: it's stopped for good, its file unfinished
            process.kill()
            process.communicate()
            raise UnfinishedInterrupt(*interrupt.args) from interrupt
        if process.returncode != 0:
            raise UnfinishedInterrupt(*interrupt.args) from interrupt  # it ended, but not cleanly: can't trust the file
        raise
    if process.returncode != 0:
        raise CommandError(args, process.returncode, (stderr or b"").decode("utf-8", "replace"))


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


def add_note(error: BaseException, message: str) -> None:
    """
    Tell what else went wrong while handling ``error``: as a note on it (Python 3.11+), else as a warning.

    For clean-ups that fail after the error that started them, which stays the one raised.
    """
    if hasattr(error, "add_note"):
        error.add_note(message)
    else:
        warnings.warn(message, RuntimeWarning, stacklevel=3)


def killall(process: str) -> None:
    """
    Quit every process named ``process``, for macOS to start it again with the settings just written.

    One that isn't running is fine: it reads them when it starts.
    """
    try:
        run(["killall", process], timeout=10)  # killall only signals: never long
    except CommandError as error:
        # 1 also means a process it found couldn't be signalled ("Operation not permitted"): only "no
        # matching processes" (in English: killall isn't localized) is a process that isn't running.
        if error.returncode != 1 or "No matching processes" not in error.stderr:
            raise


LAUNCHCTL_TIMEOUT = 60.0
"""Seconds for a ``launchctl`` call: it answers at once, unless launchd is wedged."""
PROFILER_TIMEOUT = 60.0
"""Seconds for ``system_profiler``: it takes a moment, and has hung on some Macs."""


def launchd_user_domain() -> str:
    """The launchd domain of this user's session, ``gui/<uid>``, where launch agents run."""
    import os

    return "gui/{}".format(os.getuid())


def launchd_disabled(domain: str) -> Dict[str, bool]:
    """launchctl's own on/off switches in ``domain``: label -> disabled; ``{}`` when it won't say."""
    import re

    try:
        output = run(["launchctl", "print-disabled", domain], timeout=LAUNCHCTL_TIMEOUT)
    except CommandError:
        return {}
    # Written as words or as booleans, depending on the macOS version: "disabled" and true mean off.
    found = re.findall(r'"([^"]+)"\s*=>\s*(enabled|disabled|true|false)', output)
    return {label: state in ("disabled", "true") for label, state in found}


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
# Per thread: a batch on one thread doesn't hold back another thread's restarts.
_batch = threading.local()


def restart_later(name: str, restart: Callable[[], None]) -> bool:
    """Inside :func:`batched_restarts`, note ``restart`` to run once at its end and return ``True``; else ``False``."""
    deferred: Optional[Dict[str, Callable[[], None]]] = getattr(_batch, "deferred", None)
    if deferred is None:
        return False
    deferred[name] = restart
    return True


@contextmanager
def batched_restarts() -> Iterator[None]:
    """Run each restart asked for in the block once, when it ends (even if it fails), instead of after every change."""
    if getattr(_batch, "deferred", None) is not None:
        yield  # already batching
        return
    _batch.deferred = {}
    failed: Optional[BaseException] = None
    try:
        yield
    except BaseException as error:
        failed = error
        raise
    finally:
        pending, _batch.deferred = _batch.deferred, None
        # Every restart runs, even after one fails, and never hides the error of the block itself.
        problems = []
        for name, restart in pending.items():
            try:
                restart()
            except Exception as problem:
                problems.append((name, problem))
        if problems:
            first = failed if failed is not None else problems[0][1]
            for name, reason in problems:
                if reason is not first:
                    add_note(first, "restarting {} failed too: {}".format(name, reason))
            if failed is None:
                raise first
