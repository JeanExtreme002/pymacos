# -*- coding: utf-8 -*-

"""
Run shortcuts from the Shortcuts app.

::

    macos.shortcuts.list()                           # ['Resize Image', ...]
    macos.shortcuts.run("Make GIF", input=["a.png", "b.png"])
    macos.shortcuts.run("Translate", input="Hola")   # 'Hello'

Uses the ``shortcuts`` command that ships with macOS 12 and later.
"""

import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import List, Optional, Sequence, Union

from ._system import require_macos, run as _system_run, run_bytes as _system_run_bytes
from .errors import CommandError, CommandTimeoutError, NotSupportedError, ShortcutNotFoundError

__all__ = ["list", "run", "ShortcutNotFoundError"]

_list = list

PathLike = Union[str, "os.PathLike[str]"]


def _run(args: List[str], timeout: Optional[float] = None, *, exact_newlines: bool = False) -> str:
    require_macos()
    try:
        if exact_newlines:
            # A shortcut's text is returned as it made it, "\r\n" and "\r" included (text mode makes
            # them "\n"); bytes that aren't UTF-8 still become U+FFFD, as there: it's text, not a file name.
            return _system_run_bytes(args, timeout=timeout).decode("utf-8", "replace")
        return _system_run(args, timeout=timeout)
    except NotSupportedError:
        raise NotSupportedError("running shortcuts needs macOS 12 or later (the 'shortcuts' command)") from None


_LIST_TIMEOUT = 60.0
"""Seconds for listing the shortcuts: it answers at once, unless the Shortcuts service is stuck."""


def _named(lines: str, name: str, ignore_case: bool = False) -> bool:
    # Each line reads "Name (IDENTIFIER)"; the command accepts either.
    for line in lines.splitlines():
        title, _, identifier = line.rpartition(" (")
        candidates = (line, title, identifier.rstrip(")"))
        if ignore_case:
            if name.casefold() in (candidate.casefold() for candidate in candidates):
                return True
        elif name in candidates:
            return True
    return False


def _exists(name: str) -> bool:
    return _named(_run(["shortcuts", "list", "--show-identifiers"], _LIST_TIMEOUT), name)


def _folder_exists(folder: str) -> bool:
    # Without regard to case: the command may find a folder by a name spelled otherwise, and an
    # existing folder must not be reported missing.
    return _named(_run(["shortcuts", "list", "--folders", "--show-identifiers"], _LIST_TIMEOUT), folder, True)


def list(*, folder: Optional[str] = None) -> List[str]:
    """
    Return the names of the shortcuts in the Shortcuts app, or only those in ``folder``.

    ``folder`` is a folder's name or identifier, or ``"none"`` for the
    shortcuts in no folder (so a folder named "none" is listed by its
    identifier). A folder that doesn't exist raises :class:`LookupError`,
    where an empty one gives ``[]``.

    Raises :class:`~macos.errors.CommandTimeoutError` when Shortcuts doesn't answer within a minute.
    """
    args = ["shortcuts", "list"]
    if folder is not None:
        # Joined with "=", so a folder named "-x" or "--help" is its value, not an option.
        args.append("--folder-name={}".format(folder))
    names = [name for name in _run(args, _LIST_TIMEOUT).splitlines() if name]
    if not names and folder is not None and folder != "none":
        # The command lists nothing, and succeeds, for a folder that doesn't exist: ask for the
        # folders, so a mistyped one isn't taken for an empty one. When even that fails, the
        # listing that worked stands.
        try:
            exists = _folder_exists(folder)
        except (CommandError, CommandTimeoutError):
            exists = True
        if not exists:
            raise LookupError("no shortcuts folder is named or identified {!r}".format(folder))
    return names


def run(
    name: str,
    *,
    input: Union[str, PathLike, Sequence[PathLike], None] = None,
    output: Optional[PathLike] = None,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """
    Run a shortcut and return its text output (``None`` if it produced none),
    line endings (``\\r\\n``, ``\\r``) as the shortcut wrote them.

    ``input`` is what the shortcut receives as *Shortcut Input*:

    - a :class:`str` is passed as text;
    - a :class:`pathlib.Path` (or any path-like object), or a list of them,
      is passed as files.

    Anything else (``bytes``, a number...) raises :class:`TypeError`.

    When the shortcut outputs a file (an image, a PDF...), pass ``output`` to
    save it there; the return value is then ``None``.

    ``timeout`` is how many seconds to wait for it: a shortcut still running
    then (one waiting on a prompt, say) is stopped, and
    :class:`~macos.errors.CommandTimeoutError` raised.
    """
    # The name goes last, after "--": a shortcut named "--help" or "-i" is
    # run by that name, not taken as an option. The paths before it are
    # absolute, so they can't start with "-" either.
    args = ["shortcuts", "run"]
    text_file = None

    try:
        if isinstance(input, str):
            # The command only takes input as files. A text file becomes text
            # for the shortcut, so write the string to one. Made inside the
            # try: whatever fails from here on, the file goes.
            descriptor, text_file = tempfile.mkstemp(prefix="shortcut-input-", suffix=".txt")
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(input)
            args += ["--input-path", text_file]
        elif input is not None:
            if isinstance(input, (bytes, bytearray, memoryview)) or not isinstance(input, (os.PathLike, Iterable)):
                # Bytes would be taken for a list of numbers: neither text nor paths.
                raise TypeError("input must be a str, a path or a list of paths, not {}".format(type(input).__name__))
            paths = [input] if isinstance(input, os.PathLike) else _list(input)
            for path in paths:
                if not isinstance(path, (str, os.PathLike)):
                    raise TypeError("input paths must be str or path-like, not {}".format(type(path).__name__))
                resolved = Path(path).expanduser().absolute()
                if not resolved.exists():
                    raise FileNotFoundError(str(resolved))
                args += ["--input-path", str(resolved)]

        if output is not None:
            args += ["--output-path", str(Path(output).expanduser().absolute())]
        args += ["--", name]

        try:
            result = _run(args, timeout, exact_newlines=True)
        except CommandError as error:
            # The error message is localized, so ask the app whether the shortcut
            # exists instead of parsing it. When even that fails, the run's own
            # error is the one to see, not the listing's.
            try:
                exists = _exists(name)
            except (CommandError, CommandTimeoutError):
                exists = True
            if not exists:
                raise ShortcutNotFoundError(error.cmd, error.returncode, error.stderr) from None
            raise
    finally:
        if text_file is not None:
            # A shortcut may have moved or deleted its input itself: that must not hide how the run went.
            Path(text_file).unlink(missing_ok=True)

    if output is not None or not result:
        return None
    # The command ends text output with a newline of its own.
    return result[:-1] if result.endswith("\n") else result
