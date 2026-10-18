# -*- coding: utf-8 -*-

"""
Open files, folders and URLs, with their default app or a chosen one.

::

    macos.open("report.pdf")                   # in the default app
    macos.open("https://python.org")           # in the default browser
    macos.open_with("photo.png", "Preview")

Goes through LaunchServices (the ``open`` command), exactly like
double-clicking in Finder or choosing *Open With*.
"""

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple, Union

from ._system import run as _run
from .apps import open_with

__all__ = ["open", "open_with"]

Target = Union[str, "os.PathLike[str]"]

# "https://...", "mailto:...", "x-apple.systempreferences:..." and the like.
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")


def _scheme(target: Target) -> Optional[str]:
    """A URL's scheme, lowercase (``'https'``); ``None`` for a file or folder."""
    if isinstance(target, str) and _URL.match(target) and not os.path.exists(target):
        return target.split(":", 1)[0].lower()
    return None


def _resolve(target: Target) -> Tuple[Optional[str], List[str]]:
    """
    Tell, once, whether ``target`` is a URL or a path: its scheme (``None`` for a path), and the ``open`` arguments for it.

    A URL goes with ``-u``, which ``open`` takes as a URL even when a file
    of that name appears afterwards: what was checked is what's opened.
    An empty string is neither, rather than the current directory.
    """
    if os.fspath(target) == "":
        raise ValueError("empty target: give a file, folder or URL")
    scheme = _scheme(target)
    if scheme is not None:
        return scheme, ["-u", str(target)]
    path = Path(target).expanduser().absolute()
    if not os.path.lexists(path):
        raise FileNotFoundError(str(path))
    return None, ["--", str(path)]


def _allowed(schemes: Iterable[str]) -> Set[str]:
    """The bare, lowercase names in ``schemes``: ``"https"``, ``"https:"`` and ``"https://"`` are all ``"https"``."""
    allowed = set()
    for entry in [schemes] if isinstance(schemes, str) else schemes:
        if not isinstance(entry, str):
            raise TypeError("schemes must be names like 'https', not {!r}".format(entry))
        name = entry[:-2] if entry.endswith("//") else entry
        name = name[:-1] if name.endswith(":") else name
        if not _SCHEME.fullmatch(name):  # "https://python.org" would allow every https URL, not that site
            raise ValueError("{!r} is not a URL scheme: give a name like 'https'".format(entry))
        allowed.add(name.lower())
    return allowed


def _flags(background: bool) -> List[str]:
    return ["-g"] if background else []


def open(target: Target, *, background: bool = False, schemes: Optional[Iterable[str]] = None) -> None:
    """
    Open a file, folder or URL with its default app, like double-clicking it.

    Folders open in Finder and URLs in their default app (the browser for
    ``https://``, Mail for ``mailto:``...). ``background=True`` opens it
    without bringing the app to the front.

    Any kind of URL is opened, by whichever app claims it, and a file that
    is an app or a script runs: never pass text from an untrusted source
    (a web page, a message) as is. ``schemes`` limits what's opened to those
    kinds of URL, and raises :class:`ValueError` for anything else; a file
    or folder counts as ``"file"``::

        macos.open(link, schemes={"https", "http"})   # a link from a web page: not a file, nor zoommtg://

    A string of the form ``scheme:...`` that isn't an existing path is a
    URL, so a missing ``"Report:Q3.pdf"`` goes to ``open`` as one; pass a
    :class:`~pathlib.Path` (or ``"./Report:Q3.pdf"``) to have it taken as a
    path, and a :class:`FileNotFoundError` if it isn't there. An empty
    string raises :class:`ValueError`.
    """
    allowed = None if schemes is None else _allowed(schemes)
    found, arguments = _resolve(target)  # classified once: the check and the command agree
    if allowed is not None:
        scheme = found or "file"
        if scheme not in allowed:
            raise ValueError(
                "{!r} is a {} {}, and only {} may be opened".format(
                    os.fspath(target), scheme, "URL" if scheme != "file" else "path", ", ".join(sorted(allowed)) or "nothing"
                )
            )
    _run(["open", *_flags(background), *arguments])
