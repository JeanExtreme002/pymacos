# -*- coding: utf-8 -*-

"""
Internal helpers shared by the modules that read and write documents and
media (PDFs, images, videos, sounds): writing a file in one step, checking
the files given, and a few small pieces of Cocoa they all need.
"""

import ctypes
import os
import shutil
import stat
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Union

from ._objc import NSUInteger
from .errors import MacOSError

PathLike = Union[str, "os.PathLike[str]"]


class NSRange(ctypes.Structure):
    """Foundation's ``NSRange``: where a part of a string starts, and its length, in UTF-16 units."""

    _fields_ = [("location", NSUInteger), ("length", NSUInteger)]


def existing(path: PathLike) -> Path:
    """``path`` made absolute, ``~`` expanded; :class:`FileNotFoundError` when there's nothing there."""
    resolved = Path(path).expanduser().absolute()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    return resolved


def _default_mode(folder: str) -> int:
    """
    The permissions a new file gets here: 0o666 less the umask.

    Read from a file made for it, not with ``os.umask()``, which changes the
    umask of the whole process for a moment, under any other thread too. The
    file is in a folder of its own, so it can't take the name of the output
    being staged beside it.
    """
    inside = tempfile.mkdtemp(dir=folder)
    try:
        handle = os.open(os.path.join(inside, "probe"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
        try:
            return stat.S_IMODE(os.fstat(handle).st_mode)
        finally:
            os.close(handle)
    finally:
        shutil.rmtree(inside, ignore_errors=True)


@contextmanager
def replacing(target: Path) -> Iterator[Path]:
    """
    A path to write ``target`` at, beside it, moved over ``target`` once the block ends without an error.

    Nothing is there yet: the tools that refuse to replace a file (the video
    exporter, the movie recorder) take it as well as the others. It's in a
    folder of its own in ``target``'s folder (made if missing), so the move is
    a rename on the same disk, never a copy across volumes; and it has
    ``target``'s name, so tools that go by the extension see the right one.

    The file gets the permissions ``target`` had, when it exists, or those of
    any new file (0o666 less the umask): not the private 0o600 of a
    temporary file. On an error, or when nothing was written, ``target`` is
    left as it was and the temporary folder goes.

    A symbolic link at ``target`` stays one: the file it points to is the one
    replaced. The temporary file keeps ``target``'s own name all the same, so
    the format the caller chose by it doesn't change.
    """
    name = target.name
    if os.path.islink(str(target)):
        target = Path(os.path.realpath(str(target)))
    target.parent.mkdir(parents=True, exist_ok=True)
    folder = tempfile.mkdtemp(prefix=".{}-".format(target.stem[:40] or "file"), dir=str(target.parent))
    try:
        temporary = Path(folder) / name
        yield temporary
        if not temporary.exists():
            raise MacOSError("could not write {}".format(target))
        try:
            mode = stat.S_IMODE(os.stat(str(target)).st_mode)
        except FileNotFoundError:
            mode = _default_mode(folder)
        os.chmod(str(temporary), mode)
        os.replace(str(temporary), str(target))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def write_atomically(target: PathLike, write: Callable[[str], object]) -> Path:
    """
    Call ``write`` with a path beside ``target`` to write it at, then move the file in place; return ``target``.

    See :func:`replacing`. The output may be one of the inputs, which some
    tools (PDFKit) read lazily while writing, and a failure never leaves a
    half-written file behind. ``write`` returning ``False`` is a failure.
    """
    resolved = Path(target).expanduser().absolute()
    with replacing(resolved) as temporary:
        if write(str(temporary)) is False:
            raise MacOSError("could not write {}".format(resolved))
    return resolved


def on_main_thread() -> bool:
    """Whether this is the process's main thread, the one whose run loop AppKit and the main queue use."""
    if sys.platform != "darwin":
        return threading.current_thread() is threading.main_thread()
    from . import _libc

    return bool(_libc.lib().pthread_main_np())


def require_main_thread(what: str) -> None:
    """
    Raise :class:`~macos.MacOSError` unless this is the main thread.

    Some of Apple's frameworks work only there: AppKit's text views and
    printing, WebKit's HTML reader, and the callbacks sent to the main queue,
    which only arrive while the main thread waits for them. Elsewhere they
    hang or crash the process, so this says so first.
    """
    if not on_main_thread():
        raise MacOSError(
            "{} must run on the main thread: macOS only allows it there. Call it from the "
            "main thread of the program, not from a worker thread or an executor".format(what)
        )
