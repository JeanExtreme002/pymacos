# -*- coding: utf-8 -*-

"""
Native dialogs: alerts, confirmations, text input and file pickers.

::

    macos.dialog.alert("Backup finished", detail="12 files copied")
    if macos.dialog.confirm("Delete the old logs?"):
        ...
    name = macos.dialog.prompt("What's your name?")      # None if cancelled
    path = macos.dialog.choose_file(types=["pdf"])       # None if cancelled

Dialogs are shown through AppleScript (Standard Additions), so they need no
permission and look like any other macOS dialog. They block until the user
answers; most take a ``timeout`` in seconds, after which they close as if
cancelled. Timeouts are whole seconds: a fraction is rounded up.
"""

import math
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from ._system import run as _run

__all__ = ["alert", "confirm", "prompt", "choose", "choose_file", "choose_files", "choose_folder"]

PathLike = Union[str, "os.PathLike[str]"]

_CANCEL = "cancel"
_TIMEOUT = "timeout"
_END = "\0"  # ends each chosen path: a file name can hold a newline, never a NUL


def _show(body: List[str], args: Sequence[str]) -> List[str]:
    """
    Run a dialog script and return its result lines.

    User text only ever travels as script arguments (``argv``), never spliced
    into the source. ``activate`` brings the dialog to the front; the Cancel
    button (error -128) becomes a result instead of an exception.
    """
    script = [
        "on run argv",
        "activate",
        "try",
        *body,
        "on error number -128",
        'return "{}"'.format(_CANCEL),
        "end try",
        "end run",
    ]
    command = ["osascript"]
    for line in script:
        command += ["-e", line]
    # Exact newlines: a file name the pickers return may hold a \r, which text mode would turn into \n.
    return _run([*command, "--", *args], exact_newlines=True).rstrip("\n").split("\n")


def _giving_up(timeout: Optional[float]) -> str:
    if timeout is None:
        return ""
    if timeout <= 0:
        raise ValueError("timeout must be positive, not {}".format(timeout))
    # AppleScript only counts whole seconds, and rounds a fraction to the
    # nearest one: 0.5 would become 0, which means "never give up". Round up
    # instead, so the dialog never closes before the requested time.
    return " giving up after {}".format(math.ceil(timeout))


def _gave_up_check(timeout: Optional[float]) -> List[str]:
    return ['if gave up of r then return "{}"'.format(_TIMEOUT)] if timeout is not None else []


def alert(message: str, *, detail: Optional[str] = None, timeout: Optional[float] = None) -> None:
    """Show an alert with an OK button and wait until it's dismissed (or ``timeout`` seconds pass)."""
    statement = "set r to display alert (item 1 of argv)"
    args = [message]
    if detail is not None:
        statement += " message (item 2 of argv)"
        args.append(detail)
    _show([statement + _giving_up(timeout), 'return "ok"'], args)


def confirm(
    message: str,
    *,
    title: Optional[str] = None,
    ok: str = "OK",
    cancel: str = "Cancel",
    timeout: Optional[float] = None,
) -> bool:
    """
    Ask a yes/no question and return ``True`` if the user clicked ``ok``.

    Clicking ``cancel``, pressing Escape or reaching ``timeout`` returns ``False``.
    """
    statement = (
        "set r to display dialog (item 1 of argv) buttons {(item 3 of argv), (item 2 of argv)} "
        "default button (item 2 of argv) cancel button (item 3 of argv)"
    )
    args = [message, ok, cancel]
    if title is not None:
        statement += " with title (item 4 of argv)"
        args.append(title)
    result = _show([statement + _giving_up(timeout), *_gave_up_check(timeout), 'return "ok"'], args)
    return result[0] == "ok"


def prompt(
    message: str,
    *,
    default: str = "",
    title: Optional[str] = None,
    hidden: bool = False,
    timeout: Optional[float] = None,
) -> Optional[str]:
    """
    Ask for a line of text and return it, or ``None`` if the user cancelled (or ``timeout`` passed).

    ``hidden=True`` shows dots instead of the typed characters, for passwords.
    The answer comes back on ``osascript``'s output, but ``default`` reaches
    it as an argument, which other processes of the same user can see in
    the process list while the dialog is open: don't pre-fill a secret.
    """
    statement = "set r to display dialog (item 1 of argv) default answer (item 2 of argv)"
    args = [message, default]
    if hidden:
        statement += " with hidden answer"
    if title is not None:
        statement += " with title (item 3 of argv)"
        args.append(title)
    result = _show(
        [statement + _giving_up(timeout), *_gave_up_check(timeout), 'return "ok" & linefeed & (text returned of r)'],
        args,
    )
    return "\n".join(result[1:]) if result[0] == "ok" else None


def choose(
    options: Sequence[str],
    *,
    prompt: Optional[str] = None,
    default: Optional[str] = None,
    title: Optional[str] = None,
) -> Optional[str]:
    """Let the user pick one of ``options`` from a list, and return it (``None`` if cancelled)."""
    options = [str(option) for option in options]
    if not options:
        raise ValueError("choose() needs at least one option")
    if any("\n" in option for option in options):
        raise ValueError("options can't contain newlines")
    if default is not None and default not in options:
        raise ValueError("default {!r} is not one of the options".format(default))

    statement = "set r to choose from list (items 4 thru -1 of argv) with prompt (item 1 of argv)"
    if default is not None:
        statement += " default items {(item 2 of argv)}"
    if title is not None:
        statement += " with title (item 3 of argv)"
    body = [statement, 'if r is false then return "{}"'.format(_CANCEL), 'return "ok" & linefeed & (item 1 of r)']
    result = _show(body, [prompt or "Choose an option:", default or "", title or "", *options])
    return result[1] if result[0] == "ok" else None


def _choose_file_body(
    prompt: Optional[str], types: Optional[Sequence[str]], folder: Optional[PathLike], multiple: bool
) -> Tuple[List[str], List[str]]:
    statement = "set r to choose file with prompt (item 1 of argv)"
    body: List[str] = []
    if types:
        body += [
            "set AppleScript's text item delimiters to linefeed",
            "set fileTypes to text items of (item 2 of argv)",
        ]
        statement += " of type fileTypes"
    if folder is not None:
        statement += " default location (POSIX file (item 3 of argv))"
    if multiple:
        statement += " with multiple selections allowed"
    body.append(statement)

    # Extensions ("pdf") and type identifiers ("public.image") both work.
    names = [str(kind).lstrip(".") for kind in types or []]
    args = [prompt or "Choose a file:", "\n".join(names), str(Path(folder).expanduser().resolve()) if folder else ""]
    return body, args


def _paths_body() -> List[str]:
    return [
        "if class of r is not list then set r to {r}",
        'set out to "ok" & linefeed',
        "repeat with f in r",
        "set out to out & (POSIX path of f) & (character id 0)",
        "end repeat",
        "return out",
    ]


def _paths(result: List[str]) -> List[Path]:
    """The paths :func:`_paths_body` returned, each ended by a NUL; ``[]`` if cancelled."""
    if result[0] != "ok":
        return []
    return [Path(path) for path in "\n".join(result[1:]).split(_END)[:-1] if path]


def choose_file(
    prompt: Optional[str] = None,
    *,
    types: Optional[Sequence[str]] = None,
    folder: Optional[PathLike] = None,
) -> Optional[Path]:
    """
    Show a file picker and return the chosen file, or ``None`` if cancelled.

    ``types`` limits the choice, by extension (``["pdf", "png"]``) or by type
    identifier (``["public.image"]``). ``folder`` is where the picker opens.
    """
    body, args = _choose_file_body(prompt, types, folder, multiple=False)
    found = _paths(_show(body + _paths_body(), args))
    return found[0] if found else None


def choose_files(
    prompt: Optional[str] = None,
    *,
    types: Optional[Sequence[str]] = None,
    folder: Optional[PathLike] = None,
) -> List[Path]:
    """Like :func:`choose_file`, but lets the user pick several files. Returns ``[]`` if cancelled."""
    body, args = _choose_file_body(prompt, types, folder, multiple=True)
    return _paths(_show(body + _paths_body(), args))


def choose_folder(prompt: Optional[str] = None, *, folder: Optional[PathLike] = None) -> Optional[Path]:
    """Show a folder picker and return the chosen folder, or ``None`` if cancelled."""
    statement = "set r to choose folder with prompt (item 1 of argv)"
    if folder is not None:
        statement += " default location (POSIX file (item 2 of argv))"
    args = [prompt or "Choose a folder:", str(Path(folder).expanduser().resolve()) if folder else ""]
    found = _paths(_show([statement, *_paths_body()], args))
    return found[0] if found else None
