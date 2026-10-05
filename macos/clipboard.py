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

import os
import time
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Union

from . import _objc
from ._objc import BOOL, NSInteger
from ._system import framework
from .errors import MacOSError

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
    """
    with _objc.autorelease_pool():
        pasteboard = _pasteboard()
        _objc.send(pasteboard, "clearContents", restype=NSInteger)
        # The markers go first, so a manager reading as soon as the text lands already sees them.
        for marker in _MARKERS if sensitive else ():
            if not _objc.send(
                pasteboard,
                "setData:forType:",
                _objc.nsdata(b""),
                _objc.nsstring(marker),
                argtypes=(_objc.id, _objc.id),
                restype=BOOL,
            ):
                _objc.send(pasteboard, "clearContents", restype=NSInteger)
                raise MacOSError("the pasteboard refused the sensitive-content markers")
        ok = _objc.send(
            pasteboard,
            "setString:forType:",
            _objc.nsstring(text),
            _objc.nsstring(_TYPE_STRING),
            argtypes=(_objc.id, _objc.id),
            restype=BOOL,
        )
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


def wait_for_change(*, timeout: Optional[float] = None, interval: float = 0.2) -> Optional[str]:
    """
    Wait until something new is copied, and return it as text.

    Returns ``None`` if the new content isn't text (an image, files...).
    Clearing the clipboard doesn't count as a copy. Raises
    :class:`TimeoutError` if nothing is copied within ``timeout`` seconds.
    ``interval`` is how often to check, in seconds.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    start = change_count()
    deadline = None if timeout is None else time.monotonic() + timeout
    # An app copies by clearing the clipboard, then writing to it, and the
    # clearing alone already bumps the change count: keep waiting while the
    # clipboard is empty, or the text could be read before it's written.
    while change_count() == start or _is_empty():
        if deadline is None:
            time.sleep(interval)
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("nothing was copied within {}s".format(timeout))
        # Never sleep past the deadline, even with a long interval.
        time.sleep(min(interval, remaining))
    return paste()


def watch(*, timeout: Optional[float] = None, interval: float = 0.2) -> Iterator[Optional[str]]:
    """
    Yield each new thing copied, as text (``None`` for images, files...), for a clipboard history::

        for text in macos.clipboard.watch():
            if text:
                history.append(text)

    It goes on until you ``break`` out of the loop, or ``timeout`` seconds
    pass. macOS doesn't announce copies, so it checks every ``interval``
    seconds, as :func:`wait_for_change` does.
    """
    if interval <= 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    seen = change_count()
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        # An empty clipboard is a copy being made (see wait_for_change): wait for its content.
        count = change_count()
        if count != seen and not _is_empty():
            content = paste()
            if change_count() != count:
                continue  # copied again while reading: read the newer copy instead
            seen = count
            yield content
            continue
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            return
        time.sleep(interval if remaining is None else min(interval, remaining))


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

    Save it with ``Path("pasted.png").write_bytes(macos.clipboard.paste_image())``.
    """
    with _objc.autorelease_pool():
        pasteboard = _pasteboard()
        png = _objc.send(pasteboard, "dataForType:", _objc.nsstring(_TYPE_PNG), argtypes=(_objc.id,))
        if png:
            return _objc.pybytes(png)

        # Screenshots and most apps put TIFF on the clipboard: convert it.
        tiff = _objc.send(pasteboard, "dataForType:", _objc.nsstring(_TYPE_TIFF), argtypes=(_objc.id,))
        if not tiff:
            return None
        rep = _objc.send(_objc.cls("NSBitmapImageRep"), "imageRepWithData:", tiff, argtypes=(_objc.id,))
        return _objc.png(rep) if rep else None


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
    """
    resolved = [Path(path).expanduser().absolute() for path in paths]
    if not resolved:
        raise ValueError("copy_files() needs at least one path")
    for path in resolved:
        if not os.path.lexists(path):
            raise FileNotFoundError(str(path))

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
            _objc.nsstring("NSPasteboardURLReadingFileURLsOnlyKey"),
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
