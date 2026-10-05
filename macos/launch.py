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
from typing import Iterable, List, Optional, Union

from ._system import run as _run
from .apps import open_with

__all__ = ["open", "open_with"]

Target = Union[str, "os.PathLike[str]"]

# "https://...", "mailto:...", "x-apple.systempreferences:..." and the like.
_URL = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def _scheme(target: Target) -> Optional[str]:
    """A URL's scheme, lowercase (``'https'``); ``None`` for a file or folder."""
    if isinstance(target, str) and _URL.match(target) and not os.path.exists(target):
        return target.split(":", 1)[0].lower()
    return None


def _target(target: Target) -> str:
    if _scheme(target) is not None:
        return str(target)
    path = Path(target).expanduser().absolute()
    if not os.path.lexists(path):
        raise FileNotFoundError(str(path))
    return str(path)


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
    """
    if schemes is not None:
        allowed = {scheme.lower().rstrip(":") for scheme in ([schemes] if isinstance(schemes, str) else schemes)}
        scheme = _scheme(target) or "file"
        if scheme not in allowed:
            raise ValueError(
                "{!r} is a {} {}, and only {} may be opened".format(
                    os.fspath(target), scheme, "URL" if scheme != "file" else "path", ", ".join(sorted(allowed)) or "nothing"
                )
            )
    _run(["open", *_flags(background), "--", _target(target)])
