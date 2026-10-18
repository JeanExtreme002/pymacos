# -*- coding: utf-8 -*-

"""
Internal helpers shared by the modules that read and write documents and
media (PDFs, images, videos, sounds): writing a file in one step, checking
the files given, and a few small pieces of Cocoa they all need.
"""

import ctypes
import errno
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
from .errors import MacOSError, MainThreadError

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
    being staged beside it. Read every time: ``os.umask()`` may have changed
    it since the last write (a daemon going private before a secrets file).
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


_XATTR_NOFOLLOW = 0x0001

_STALE_ATTRIBUTES = (
    b"com.apple.ResourceFork",
    b"com.apple.FinderInfo",  # the old format's type and creator, beside the Finder flags
    b"com.apple.TextEncoding",
    b"com.apple.decmpfs",
    b"com.apple.provenance",  # the kernel's own
    b"com.apple.rootless",
)
"""Extended attributes that describe the old content, or that macOS manages itself: never copied to the new file."""


def _xattr_lib() -> ctypes.CDLL:
    """libSystem, with the calls :func:`_carry_metadata` needs declared (in :func:`macos._libc.lib`)."""
    from . import _libc

    return _libc.lib()


@contextmanager
def _carry_metadata(source: Path, destination: Path) -> Iterator[None]:
    """
    Copy ``source``'s extended attributes to ``destination``; its access control list once the block moved it in place.

    Only the attributes ``destination`` doesn't have: one the writer set on
    the new file (a tool's own) wins over the old file's. The list goes on
    last, on the file in place, never on the staged one: copied there, an
    entry that denies deleting it would leave the staging folder behind when
    the move fails, and one that denies changing it would keep it there.
    Never fails: a volume without extended attributes, or a list that isn't
    this user's to copy, leaves the new file as it was written rather than
    losing the save. Nothing is done when the block raises.
    """
    if sys.platform != "darwin":
        yield
        return
    from . import _libc

    try:
        libc = _xattr_lib()
    except OSError:  # no libSystem to load: nothing can be carried, and the save still goes ahead
        yield
        return
    old, new = os.fsencode(str(source)), os.fsencode(str(destination))
    size = libc.listxattr(old, None, 0, _XATTR_NOFOLLOW)
    names = ctypes.create_string_buffer(max(size, 1))
    size = libc.listxattr(old, names, size, _XATTR_NOFOLLOW) if size > 0 else 0
    for attribute in names.raw[: max(size, 0)].split(b"\0"):
        if not attribute or attribute in _STALE_ATTRIBUTES or attribute.startswith(b"com.apple.cs."):
            continue
        length = libc.getxattr(old, attribute, None, 0, 0, _XATTR_NOFOLLOW)
        if length < 0:
            continue  # gone since, or not readable
        value = ctypes.create_string_buffer(max(length, 1))
        length = libc.getxattr(old, attribute, value, length, 0, _XATTR_NOFOLLOW)
        if length >= 0:
            # Created only where missing: EEXIST means the writer set it, and the volume may refuse any.
            libc.setxattr(new, attribute, value, length, 0, _XATTR_NOFOLLOW | _libc.XATTR_CREATE)
    access = libc.acl_get_file(old, _libc.ACL_TYPE_EXTENDED)  # None: the old file has no list
    try:
        yield
        if access:
            libc.acl_set_file(old, _libc.ACL_TYPE_EXTENDED, access)  # best effort too: its result is left unread
    finally:
        if access:
            libc.acl_free(access)


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

    The new file also gets, on macOS, what the old one carried beside its
    content: its Finder tags and comment, where it was downloaded from, its
    quarantine flag, any other extended attribute the writer didn't set
    itself, and its access control list. Those that describe the old content
    (its resource fork, Finder type and creator, text encoding, code
    signature) don't carry over, nor does anything the volume refuses. It's
    another file all the same: a hard link to the old one keeps the old
    content, and its creation date is the new file's.

    A ``target`` that is a folder, or can't be looked up (a symbolic link
    that loops), raises before the block runs, not once the work is done:
    :class:`IsADirectoryError` for a folder, the :class:`OSError` of the
    lookup otherwise.
    """
    name = target.name
    try:
        if stat.S_ISDIR(os.stat(str(target)).st_mode):
            raise IsADirectoryError(errno.EISDIR, "the output is a folder, not a file", str(target))
    except FileNotFoundError:
        pass  # a new file, or a symbolic link to one
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
            # The permission bits only: a setuid, setgid or sticky bit on the old file isn't
            # something the new content earned.
            mode = stat.S_IMODE(os.stat(str(target)).st_mode) & 0o777
            replaced = True
        except FileNotFoundError:
            mode, replaced = _default_mode(folder), False
        os.chmod(str(temporary), mode)
        if not replaced:
            os.replace(str(temporary), str(target))
        else:
            # The access list goes on once the new file is in place, after the chmod too: an
            # entry that denies changing the permissions, or deleting the file, mustn't stop either.
            with _carry_metadata(target, temporary):
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
    Raise :class:`~macos.MainThreadError` unless this is the main thread.

    Some of Apple's frameworks work only there: AppKit's text views and
    printing, WebKit's HTML reader, and the callbacks sent to the main queue,
    which only arrive while the main thread waits for them. Elsewhere they
    hang or crash the process, so this says so first.
    """
    if not on_main_thread():
        raise MainThreadError(
            "{} must run on the main thread: macOS only allows it there. Call it from the "
            "main thread of the program, not from a worker thread or an executor".format(what)
        )
