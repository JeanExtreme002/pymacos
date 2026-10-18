# -*- coding: utf-8 -*-

"""
Read and write the system clipboard (the general pasteboard).

::

    macos.clipboard.copy("hello")
    macos.clipboard.paste()      # 'hello'
    macos.clipboard.clear()

Uses ``NSPasteboard`` directly, so non-ASCII text round-trips correctly
regardless of the terminal's locale (``pbcopy``/``pbpaste`` mangle it unless
``LANG`` is a UTF-8 locale).
"""

import math
import os
import time
import warnings
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Union

from . import _cf, _objc
from ._objc import BOOL, NSInteger
from ._system import framework
from .errors import MacOSError, WaitTimeoutError

__all__ = [
    "copy",
    "paste",
    "clear",
    "change_count",
    "wait_for_change",
    "watch",
    "copy_image",
    "paste_image",
    "has_image",
    "copy_files",
    "paste_files",
]

_TYPE_STRING = "public.utf8-plain-text"  # NSPasteboardTypeString
_TYPE_PNG = "public.png"  # NSPasteboardTypePNG
_TYPE_TIFF = "public.tiff"  # NSPasteboardTypeTIFF
# The longest one sleep of a wait: time.sleep overflows on an infinite or huge value, and an
# infinite interval is fine with a deadline (the wait sleeps until it), even an infinite one.
_LONGEST_SLEEP = 86400.0
# The nspasteboard.org markers clipboard managers (Alfred, Raycast, Maccy,
# Paste, 1Password's own...) honor: Concealed, don't show or store the
# contents; Transient, don't keep them in the history. Their value is unused.
_MARKERS = ("org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType")


def _pasteboard() -> int:
    framework("AppKit")
    return _objc.send(_objc.cls("NSPasteboard"), "generalPasteboard")


def copy(text: str, *, sensitive: bool = False) -> None:
    """
    Replace the clipboard contents with ``text``.

    ``sensitive=True``, for a password or a token, also marks it as concealed
    and transient, so clipboard managers that follow the nspasteboard.org
    convention (most do) neither show it nor keep it in their history. Apps
    pasting it get the text as usual. It's a request, not a protection: any
    app can still read the clipboard; clear it after use.

    ``text`` that isn't a ``str`` raises ``TypeError``, and one that can't be
    encoded as UTF-8 (a lone surrogate) ``UnicodeEncodeError``; either way the
    clipboard keeps what it held.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a str, not {}".format(type(text).__name__))
    with _objc.autorelease_pool():
        pasteboard = _pasteboard()
        # Built before the clipboard is cleared: text that can't be encoded leaves it as it was.
        string = _objc.nsstring(text)
        markers = [(_objc.nsdata(b""), _objc.nsstring(marker)) for marker in (_MARKERS if sensitive else ())]
        _objc.send(pasteboard, "clearContents", restype=NSInteger)
        # The markers go first, so a manager reading as soon as the text lands already sees them.
        for data, marker in markers:
            if not _objc.send(pasteboard, "setData:forType:", data, marker, argtypes=(_objc.id, _objc.id), restype=BOOL):
                _objc.send(pasteboard, "clearContents", restype=NSInteger)
                raise MacOSError("the pasteboard refused the sensitive-content markers")
        ok = _objc.send(
            pasteboard,
            "setString:forType:",
            string,
            _objc.nsstring(_TYPE_STRING),
            argtypes=(_objc.id, _objc.id),
            restype=BOOL,
        )
        if not ok and markers:
            # Not the markers alone: watchers would take them for a copy with no text.
            _objc.send(pasteboard, "clearContents", restype=NSInteger)
    if not ok:
        raise MacOSError("the pasteboard refused the text")


def paste() -> Optional[str]:
    """Return the text on the clipboard, or ``None`` if it holds no text (e.g. an image)."""
    with _objc.autorelease_pool():
        value = _objc.send(_pasteboard(), "stringForType:", _objc.nsstring(_TYPE_STRING), argtypes=(_objc.id,))
        return _objc.pystring(value)


def clear() -> None:
    """Empty the clipboard."""
    with _objc.autorelease_pool():
        _objc.send(_pasteboard(), "clearContents", restype=NSInteger)


def change_count() -> int:
    """
    A counter that increases every time any app changes the clipboard.

    Compare two readings to detect a change without reading the contents.
    """
    with _objc.autorelease_pool():
        return _objc.send(_pasteboard(), "changeCount", restype=NSInteger)


def wait_for_change(
    *, timeout: Optional[float] = None, interval: float = 0.2, include_sensitive: bool = True
) -> Optional[str]:
    """
    Wait until something new is copied, and return it as text.

    Returns ``None`` if the new content isn't text (an image, files...).
    Clearing the clipboard doesn't count as a copy. Raises
    :class:`~macos.WaitTimeoutError` (a ``TimeoutError``) if nothing is copied
    within ``timeout`` seconds.
    ``interval`` is how often to check, in seconds.
    ``include_sensitive=False`` waits on past a copy marked as concealed or
    transient (a password, see :func:`watch`), for the next one. By default
    every copy counts, and will: one copy was asked for, not a history.
    ``timeout`` is the total time waited, however many copies are passed over.
    """
    _check_wait(timeout, interval)
    start = change_count()
    deadline = None if timeout is None else time.monotonic() + timeout
    last = False  # past the deadline, a copy overwritten while read: the newer one is read once more
    while True:
        # An app copies by clearing the clipboard, then writing to it, and the
        # clearing alone already bumps the change count: keep waiting while the
        # clipboard is empty, or the text could be read before it's written.
        while True:
            count = change_count()
            if count != start and not _is_empty():
                break
            if deadline is None:
                time.sleep(min(interval, _LONGEST_SLEEP))
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WaitTimeoutError("nothing was copied within {}s".format(timeout))
            # Never sleep past the deadline, even with a long interval.
            time.sleep(min(interval, remaining, _LONGEST_SLEEP))
        content = paste()
        if include_sensitive:
            return content
        skipped = _is_sensitive()
        recopied = change_count() != count
        if not skipped and (not recopied or last):
            return content
        # The inner loop leaves before its deadline check when the count has
        # already moved: check it here, or a stream of copies would wait forever.
        expired = deadline is not None and time.monotonic() >= deadline
        if recopied and not last:
            # Copied again while reading: read the newer copy instead (see watch).
            # Something was copied in time, so past the deadline it's read once
            # more and returned, however many copies follow: no timeout error.
            last = expired
            continue
        if expired:
            raise WaitTimeoutError("nothing was copied within {}s".format(timeout))
        start = count  # a concealed copy: wait for the next one


def watch(
    *, timeout: Optional[float] = None, interval: float = 0.2, include_sensitive: Optional[bool] = None
) -> Iterator[Optional[str]]:
    """
    Yield each new thing copied, as text (``None`` for images, files...), for a clipboard history::

        for text in macos.clipboard.watch(include_sensitive=False):
            if text:
                history.append(text)

    It goes on until you ``break`` out of the loop, or ``timeout`` seconds
    pass. macOS doesn't announce copies, so it checks every ``interval``
    seconds, as :func:`wait_for_change` does.

    ``include_sensitive=False`` skips what's marked as concealed or transient
    (a password copied with ``copy(sensitive=True)``, or by a password
    manager), as clipboard managers do: a history shouldn't keep it. Say
    which you want: today every copy is yielded unless told otherwise, and
    pymacos 2.0 will skip the concealed ones by default, so leaving it out
    warns (``DeprecationWarning``).

    ``timeout`` is the total time, the loop's own included: copies keep
    coming while you handle one, and it still stops once it's passed.
    """
    _check_wait(timeout, interval)
    if include_sensitive is None:
        warnings.warn(
            "macos.clipboard.watch() yields concealed copies (passwords) unless include_sensitive=False; "
            "pymacos 2.0 will skip them by default: pass include_sensitive=True to keep them, or False to skip them",
            DeprecationWarning,
            stacklevel=2,  # at the call: not a generator, so the warning names the line that left it out
        )
        include_sensitive = True
    return _watch(timeout, interval, include_sensitive)


def _watch(timeout: Optional[float], interval: float, include_sensitive: bool) -> Iterator[Optional[str]]:
    seen = change_count()
    deadline = None if timeout is None else time.monotonic() + timeout
    last = False  # past the deadline, a copy overwritten while read: the newer one is read once more
    while True:
        # An empty clipboard is a copy being made (see wait_for_change): wait for its content.
        count = change_count()
        if count != seen and not _is_empty():
            content = paste()
            skipped = not include_sensitive and _is_sensitive()
            # Copied again while reading: skip this one, and read the newer copy instead.
            recopied = change_count() != count
            if not recopied or last:
                seen = count
                if not skipped:
                    yield content
            # Copies landing while the loop's body ran would come back here
            # without ever reaching the idle branch's deadline check. A copy
            # overwritten at the deadline still has its newer one read, once.
            if deadline is not None and time.monotonic() >= deadline:
                if not recopied or last:
                    return
                last = True
            continue
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return
        time.sleep(min(interval, _LONGEST_SLEEP) if remaining is None else min(interval, remaining, _LONGEST_SLEEP))


def _check_wait(timeout: Optional[float], interval: float) -> None:
    """Refuse a ``timeout`` or ``interval`` that would hang the wait, or fail inside ``time.sleep``."""
    # NaN passes "<= 0", and an infinite interval with no deadline would never look again.
    if not math.isfinite(interval) and not (interval == math.inf and timeout is not None):
        raise ValueError("interval must be a positive number of seconds, not {}".format(interval))
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    if timeout is not None and math.isnan(timeout):
        raise ValueError("timeout must be a number of seconds, not nan")


def _is_sensitive() -> bool:
    """Whether what's on the clipboard carries a concealed or transient marker (see :func:`copy`)."""
    with _objc.autorelease_pool():
        types = _objc.send(_pasteboard(), "types")
        found = {_objc.pystring(kind) for kind in _objc.nsarray(types)}
    return any(marker in found for marker in _MARKERS)


def _is_empty() -> bool:
    with _objc.autorelease_pool():
        types = _objc.send(_pasteboard(), "types")
        return not types or not _objc.send(types, "count", restype=_objc.NSUInteger)


def copy_image(image: Union[bytes, str, "os.PathLike[str]"]) -> None:
    """
    Put an image on the clipboard, from a file path or the file's bytes.

    Any format macOS can open works (PNG, JPEG, HEIC, GIF, TIFF, PDF...).
    Other apps receive it the same way as an image copied in Preview.
    """
    if isinstance(image, (bytes, bytearray)):
        data = bytes(image)
    else:
        with open(os.fspath(image), "rb") as file:
            data = file.read()
    framework("AppKit")  # defines NSImage
    with _objc.autorelease_pool():
        picture = _objc.send(_objc.cls("NSImage"), "alloc")
        picture = _objc.send(picture, "initWithData:", _objc.nsdata(data), argtypes=(_objc.id,))
        if not picture:
            raise ValueError("not an image format macOS can read")
        _objc.send(picture, "autorelease")

        array = _objc.nsarray_of([picture])
        pasteboard = _pasteboard()
        _objc.send(pasteboard, "clearContents", restype=NSInteger)
        if not _objc.send(pasteboard, "writeObjects:", array, argtypes=(_objc.id,), restype=BOOL):
            raise MacOSError("the pasteboard refused the image")


def paste_image() -> Optional[bytes]:
    """
    Return the image on the clipboard as PNG bytes, or ``None`` if it holds no image.

    An image macOS can't read or convert to PNG (an empty or corrupt one, which
    :func:`has_image` still reports) raises :class:`~macos.errors.MacOSError`.

    Save it with ``Path("pasted.png").write_bytes(macos.clipboard.paste_image())``.
    """
    with _objc.autorelease_pool():
        pasteboard = _pasteboard()
        png = _objc.send(pasteboard, "dataForType:", _objc.nsstring(_TYPE_PNG), argtypes=(_objc.id,))
        data = _objc.pybytes(png) if png else b""
        if data:
            return data

        # Screenshots and most apps put TIFF on the clipboard: convert it.
        tiff = _objc.send(pasteboard, "dataForType:", _objc.nsstring(_TYPE_TIFF), argtypes=(_objc.id,))
        if not tiff:
            if png:  # an empty PNG entry: has_image() says there's an image, so not None
                raise MacOSError("the clipboard's PNG image is empty")
            return None
        rep = _objc.send(_objc.cls("NSBitmapImageRep"), "imageRepWithData:", tiff, argtypes=(_objc.id,))
        return _objc.png(rep)  # raises for TIFF macOS can't decode (no rep), as for one it can't encode


def has_image() -> bool:
    """Whether the clipboard holds an image, without converting it."""
    with _objc.autorelease_pool():
        types = _objc.nsarray_of([_objc.nsstring(_TYPE_PNG), _objc.nsstring(_TYPE_TIFF)])
        return bool(_objc.send(_pasteboard(), "availableTypeFromArray:", types, argtypes=(_objc.id,)))


def copy_files(paths: Iterable[Union[str, "os.PathLike[str]"]]) -> None:
    """
    Put files on the clipboard, as if they were copied in Finder.

    Pasting in Finder then copies the files there, and apps like Mail or Slack
    attach them.

    ``paths`` is a list: a single path raises ``TypeError`` (pass ``[path]``).
    A missing path and ``""`` raise ``FileNotFoundError``; a path in a folder
    you can't open, ``PermissionError``. Either way the clipboard keeps what
    it held.
    """
    if isinstance(paths, (str, bytes, os.PathLike)):
        raise TypeError("paths must be a list of paths, not a single path: use [{!r}]".format(paths))
    paths = list(paths)
    if not paths:
        raise ValueError("copy_files() needs at least one path")
    resolved = []
    for path in paths:
        if not os.fspath(path):
            raise FileNotFoundError("")  # as os.stat("") does: Path("") would be the current folder
        target = Path(path).expanduser().absolute()
        # os.lstat, not os.path.lexists: that says "missing" for a file it may not look at, too.
        # A broken link is still copied, as Finder copies it.
        try:
            os.lstat(target)
        except (FileNotFoundError, NotADirectoryError):
            raise FileNotFoundError(str(target)) from None
        resolved.append(target)

    with _objc.autorelease_pool():
        urls = [_objc.file_url(path) for path in resolved]
        pasteboard = _pasteboard()
        _objc.send(pasteboard, "clearContents", restype=NSInteger)
        if not _objc.send(pasteboard, "writeObjects:", _objc.nsarray_of(urls), argtypes=(_objc.id,), restype=BOOL):
            raise MacOSError("the pasteboard refused the files")


def paste_files() -> List[Path]:
    """Return the files on the clipboard (e.g. copied in Finder), or ``[]`` if there are none."""
    with _objc.autorelease_pool():
        pasteboard = _pasteboard()
        only_files = _objc.send(
            _objc.cls("NSDictionary"),
            "dictionaryWithObject:forKey:",
            _objc.send(_objc.cls("NSNumber"), "numberWithBool:", True, argtypes=(BOOL,)),
            _cf.constant(framework("AppKit"), "NSPasteboardURLReadingFileURLsOnlyKey"),  # the real key, not its name
            argtypes=(_objc.id, _objc.id),
        )
        urls = _objc.send(
            pasteboard,
            "readObjectsForClasses:options:",
            _objc.nsarray_of([_objc.cls("NSURL")]),
            only_files,
            argtypes=(_objc.id, _objc.id),
        )
        paths = (_objc.pystring(_objc.send(url, "path")) for url in _objc.nsarray(urls))
        return [Path(path) for path in paths if path]
