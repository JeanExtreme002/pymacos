# -*- coding: utf-8 -*-

"""
Finder operations: reveal files, move them to the Trash, manage tags and aliases, and watch folders.

::

    macos.finder.reveal("report.pdf")
    macos.finder.trash("old.log")                 # Path in ~/.Trash
    macos.finder.add_tags("report.pdf", "Work")
    macos.finder.tags("report.pdf")               # ['Work']
    macos.finder.resolve_alias("Projects alias")  # PosixPath('/Users/alice/Documents/Projects')

    for event in macos.finder.watch("~/Downloads"):
        print(event.kind, event.path)             # created /Users/alice/Downloads/report.pdf

Trash and tags go through Foundation (``NSFileManager``/``NSURL``), the same
APIs Finder itself uses: a trashed file can be restored with *Put Back*, and
tags show up in Finder's sidebar and in Spotlight.
"""

import collections
import ctypes
import fnmatch
import os
import stat
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple, Union

from . import _cf, _libc, _objc, defaults, spotlight
from ._objc import BOOL, NSUInteger
from ._system import applescript, framework, killall, require_macos, restart_later, run as _run
from .errors import MacOSError

__all__ = [
    "reveal",
    "trash",
    "tags",
    "set_tags",
    "add_tags",
    "remove_tags",
    "thumbnail",
    "is_alias",
    "resolve_alias",
    "make_alias",
    "Event",
    "watch",
    "wait_for_change",
    "selection",
    "current_folder",
    "compress",
    "extract",
    "quick_look",
    "show_hidden_files",
    "set_show_hidden_files",
    "show_extensions",
    "set_show_extensions",
    "show_path_bar",
    "set_show_path_bar",
    "show_status_bar",
    "set_show_status_bar",
    "show_desktop_icons",
    "set_show_desktop_icons",
    "default_view",
    "set_default_view",
    "show_library_folder",
    "set_show_library_folder",
    "new_window_folder",
    "set_new_window_folder",
    "search_scope",
    "set_search_scope",
    "show_full_path_in_title",
    "set_show_full_path_in_title",
    "restart",
    "folders_first",
    "set_folders_first",
    "extension_change_warning",
    "set_extension_change_warning",
    "remove_old_trash_items",
    "set_remove_old_trash_items",
    "drives_on_desktop",
    "set_show_drives_on_desktop",
    "quit_menu",
    "set_quit_menu",
    "desktop_view",
    "set_desktop_view",
    "set_icon",
    "remove_icon",
    "has_custom_icon",
    "largest",
]

PathLike = Union[str, "os.PathLike[str]"]


def _existing(path: PathLike) -> Path:
    resolved = Path(path).expanduser().absolute()
    if not os.path.lexists(resolved):
        raise FileNotFoundError(str(resolved))
    return resolved


def _raise(error: ctypes.c_void_p, what: str) -> None:
    raise MacOSError("{}: {}".format(what, _objc.error_message(error) or "unknown error"))


@lru_cache(maxsize=None)
def _tag_names_key() -> int:
    return ctypes.c_void_p.in_dll(framework("Foundation"), "NSURLTagNamesKey").value or 0


def reveal(path: PathLike) -> None:
    """Open a Finder window with ``path`` selected."""
    # Through LaunchServices (`open -R`), which, unlike asking NSWorkspace,
    # also brings Finder to the front when called from a script.
    _run(["open", "-R", str(_existing(path))])


def trash(path: PathLike) -> Path:
    """
    Move ``path`` to the Trash and return where it ended up.

    Unlike deleting it, the file can be restored from the Trash with
    *Put Back*.
    """
    source = _existing(path)
    with _objc.autorelease_pool():
        manager = _objc.send(_objc.cls("NSFileManager"), "defaultManager")
        resulting = ctypes.c_void_p()
        error = ctypes.c_void_p()
        ok = _objc.send(
            manager,
            "trashItemAtURL:resultingItemURL:error:",
            _objc.file_url(source),
            ctypes.byref(resulting),
            ctypes.byref(error),
            argtypes=(_objc.id, ctypes.c_void_p, ctypes.c_void_p),
            restype=BOOL,
        )
        if not ok:
            _raise(error, "could not move {} to the Trash".format(source))
        return Path(_objc.pystring(_objc.send(resulting.value, "path")) or "")


def tags(path: PathLike) -> List[str]:
    """Return the Finder tags on ``path`` (e.g. ``['Red', 'Work']``)."""
    target = _existing(path)
    with _objc.autorelease_pool():
        value = ctypes.c_void_p()
        error = ctypes.c_void_p()
        ok = _objc.send(
            _objc.file_url(target),
            "getResourceValue:forKey:error:",
            ctypes.byref(value),
            _tag_names_key(),
            ctypes.byref(error),
            argtypes=(ctypes.c_void_p, _objc.id, ctypes.c_void_p),
            restype=BOOL,
        )
        if not ok:
            _raise(error, "could not read the tags of {}".format(target))
        return [name for name in (_objc.pystring(item) for item in _objc.nsarray(value.value)) if name]


def set_tags(path: PathLike, names: Iterable[str]) -> None:
    """Replace the Finder tags on ``path`` with ``names`` (an empty list removes them all)."""
    target = _existing(path)
    names = list(dict.fromkeys(names))  # drop duplicates, keep the order
    with _objc.autorelease_pool():
        objects = (ctypes.c_void_p * len(names))(*[_objc.nsstring(name) for name in names])
        array = _objc.send(
            _objc.cls("NSArray"),
            "arrayWithObjects:count:",
            objects,
            len(names),
            argtypes=(ctypes.c_void_p, NSUInteger),
        )
        error = ctypes.c_void_p()
        ok = _objc.send(
            _objc.file_url(target),
            "setResourceValue:forKey:error:",
            array,
            _tag_names_key(),
            ctypes.byref(error),
            argtypes=(_objc.id, _objc.id, ctypes.c_void_p),
            restype=BOOL,
        )
        if not ok:
            _raise(error, "could not set the tags of {}".format(target))


def add_tags(path: PathLike, *names: str) -> List[str]:
    """Add tags to ``path``, keeping the ones it has. Return the new list of tags."""
    updated = list(dict.fromkeys([*tags(path), *names]))
    set_tags(path, updated)
    return updated


def remove_tags(path: PathLike, *names: str) -> List[str]:
    """Remove tags from ``path`` (missing ones are ignored). Return the new list of tags."""
    updated = [name for name in tags(path) if name not in names]
    set_tags(path, updated)
    return updated


_MAX_THUMBNAIL = 4096


@lru_cache(maxsize=None)
def _graphics() -> ctypes.CDLL:
    cg = framework("CoreGraphics")
    cg.CGImageGetWidth.argtypes = (ctypes.c_void_p,)
    cg.CGImageGetWidth.restype = ctypes.c_size_t
    cg.CGImageGetHeight.argtypes = (ctypes.c_void_p,)
    cg.CGImageGetHeight.restype = ctypes.c_size_t
    cg.CGColorSpaceCreateDeviceRGB.argtypes = ()
    cg.CGColorSpaceCreateDeviceRGB.restype = ctypes.c_void_p
    cg.CGColorSpaceRelease.argtypes = (ctypes.c_void_p,)
    cg.CGColorSpaceRelease.restype = None
    cg.CGBitmapContextCreate.argtypes = (
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_uint32,
    )
    cg.CGBitmapContextCreate.restype = ctypes.c_void_p
    cg.CGContextSetInterpolationQuality.argtypes = (ctypes.c_void_p, ctypes.c_int32)
    cg.CGContextSetInterpolationQuality.restype = None
    cg.CGContextDrawImage.argtypes = (ctypes.c_void_p, _objc.CGRect, ctypes.c_void_p)
    cg.CGContextDrawImage.restype = None
    cg.CGBitmapContextCreateImage.argtypes = (ctypes.c_void_p,)
    cg.CGBitmapContextCreateImage.restype = ctypes.c_void_p
    cg.CGContextRelease.argtypes = (ctypes.c_void_p,)
    cg.CGContextRelease.restype = None
    return cg


def _fit(image: int, size: int) -> Optional[int]:
    """A new ``CGImage`` scaled so its largest side is ``size`` pixels (caller releases it), or ``None``."""
    cg = _graphics()
    width, height = cg.CGImageGetWidth(image), cg.CGImageGetHeight(image)
    scale = size / max(width, height, 1)
    new_width, new_height = max(1, round(width * scale)), max(1, round(height * scale))
    space = cg.CGColorSpaceCreateDeviceRGB()
    # 8 bits per component, premultiplied alpha last (kCGImageAlphaPremultipliedLast).
    context = cg.CGBitmapContextCreate(None, new_width, new_height, 8, 0, space, 1)
    cg.CGColorSpaceRelease(space)
    if not context:
        return None
    try:
        cg.CGContextSetInterpolationQuality(context, 3)  # kCGInterpolationHigh
        rect = _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(new_width, new_height))
        cg.CGContextDrawImage(context, rect, image)
        return cg.CGBitmapContextCreateImage(context) or None
    finally:
        cg.CGContextRelease(context)


@lru_cache(maxsize=None)
def _quicklook() -> ctypes.CDLL:
    quicklook = framework("QuickLook")
    quicklook.QLThumbnailImageCreate.argtypes = (ctypes.c_void_p, ctypes.c_void_p, _objc.CGSize, ctypes.c_void_p)
    quicklook.QLThumbnailImageCreate.restype = ctypes.c_void_p
    return quicklook


def _encode(image: Optional[int]) -> bytes:
    """Encode an owned ``CGImage`` as PNG bytes and release it."""
    if not image:
        raise MacOSError("the preview could not be drawn")
    return _objc.cgimage_png(image)


def thumbnail(path: PathLike, *, size: int = 256) -> bytes:
    """
    Return a preview of ``path`` as PNG bytes, like the ones Finder shows.

    Documents, images, videos and PDFs get a Quick Look preview of their
    content; anything else (apps, folders, unknown files) gets its icon.
    ``size`` is the largest side, in pixels (up to 4096)::

        Path("preview.png").write_bytes(macos.finder.thumbnail("report.pdf"))
    """
    if not 0 < size <= _MAX_THUMBNAIL:
        raise ValueError("size must be from 1 to {}, not {}".format(_MAX_THUMBNAIL, size))
    target = _existing(path)
    framework("AppKit")
    with _objc.autorelease_pool():
        image = _quicklook().QLThumbnailImageCreate(None, _objc.file_url(target), _objc.CGSize(size, size), None)
        if image:
            return _encode(image)

        # No Quick Look preview: fall back to the file's icon, drawn at `size`.
        workspace = _objc.send(_objc.cls("NSWorkspace"), "sharedWorkspace")
        icon = _objc.send(workspace, "iconForFile:", _objc.nsstring(str(target)), argtypes=(_objc.id,))
        rect = _objc.CGRect(_objc.CGPoint(0, 0), _objc.CGSize(size, size))
        cgimage = _objc.send(
            icon,
            "CGImageForProposedRect:context:hints:",
            ctypes.byref(rect),
            None,
            None,
            argtypes=(ctypes.c_void_p, _objc.id, _objc.id),
            restype=ctypes.c_void_p,
        )
        if not cgimage:
            raise MacOSError("the icon of {} could not be drawn".format(target))
        # On a Retina display the icon comes out at twice the size: scale it.
        return _encode(_fit(cgimage, size))


# Finder aliases: files that point to another file or folder, and keep finding
# it when it's moved or renamed. Unlike symbolic links, Python can't follow them.

_SUITABLE_FOR_BOOKMARK_FILE = 1 << 10  # NSURLBookmarkCreationSuitableForBookmarkFile
_WITHOUT_UI = 1 << 8  # NSURLBookmarkResolutionWithoutUI: never ask the user anything
_MAX_HOPS = 32  # an alias of an alias of...: stop at loops


def _is_finder_alias(path: Path) -> bool:
    with _objc.autorelease_pool():
        value = ctypes.c_void_p()
        error = ctypes.c_void_p()
        key = ctypes.c_void_p.in_dll(framework("Foundation"), "NSURLIsAliasFileKey").value
        ok = _objc.send(
            _objc.file_url(path),
            "getResourceValue:forKey:error:",
            ctypes.byref(value),
            key,
            ctypes.byref(error),
            argtypes=(ctypes.c_void_p, _objc.id, ctypes.c_void_p),
            restype=BOOL,
        )
        if not ok:
            _raise(error, "could not read {}".format(path))
        # Foundation counts symbolic links as aliases too; a Finder alias isn't one.
        return bool(value.value and _objc.send(value.value, "boolValue", restype=BOOL)) and not path.is_symlink()


def is_alias(path: PathLike) -> bool:
    """
    Whether ``path`` is a Finder alias (made with *File › Make Alias*).

    Symbolic links aren't aliases: check them with :meth:`pathlib.Path.is_symlink`.
    """
    return _is_finder_alias(_existing(path))


def resolve_alias(path: PathLike) -> Path:
    """
    Return the file or folder a Finder alias points to, even after it was moved or renamed.

    ``os.path.realpath()`` and :meth:`pathlib.Path.resolve` only follow
    symbolic links: to Python, an alias is a small file of its own. This
    follows aliases and symbolic links, one after another, and returns any
    other path as it is, so it's safe to call on every path::

        for item in Path("~/Desktop").expanduser().iterdir():
            print(item.name, "->", macos.finder.resolve_alias(item))

    Raises :class:`FileNotFoundError` when the original is gone. It never
    shows a dialog, but an alias to a network share may mount it.
    """
    current = _existing(path)
    for _ in range(_MAX_HOPS):
        if not (current.is_symlink() or _is_finder_alias(current)):
            return current
        with _objc.autorelease_pool():
            error = ctypes.c_void_p()
            resolved = _objc.send(
                _objc.cls("NSURL"),
                "URLByResolvingAliasFileAtURL:options:error:",
                _objc.file_url(current),
                _WITHOUT_UI,
                ctypes.byref(error),
                argtypes=(_objc.id, NSUInteger, ctypes.c_void_p),
            )
            target = _objc.pystring(_objc.send(resolved, "path")) if resolved else None
            if not target:
                raise FileNotFoundError(
                    "the original of the alias {} was not found: {}".format(
                        current, _objc.error_message(error) or "it may have been deleted"
                    )
                )
        current = Path(target)
    raise MacOSError("{} is part of a loop of aliases".format(path))


def _display_name(path: Path) -> str:
    """The name Finder shows, e.g. ``'Macintosh HD'`` for ``/``, which has no name of its own."""
    with _objc.autorelease_pool():
        manager = _objc.send(_objc.cls("NSFileManager"), "defaultManager")
        name = _objc.pystring(
            _objc.send(manager, "displayNameAtPath:", _objc.nsstring(str(path)), argtypes=(_objc.id,))
        )
    return name or "Disk"


def make_alias(target: PathLike, alias: Optional[PathLike] = None) -> Path:
    """
    Create a Finder alias of ``target``, like *File › Make Alias*, and return its path.

    By default it goes next to ``target``, named ``"<name> alias"`` as Finder
    does. ``alias`` is the path to create, or a folder to create it in::

        macos.finder.make_alias("report.pdf")                      # report.pdf alias
        macos.finder.make_alias("report.pdf", "~/Desktop")         # ~/Desktop/report.pdf alias
        macos.finder.make_alias("report.pdf", "~/Desktop/Report")  # named Report

    Raises :class:`FileExistsError` if something already has the alias's path.
    The alias of a disk (``"/"``) is named after it (``"Macintosh HD alias"``)
    and needs ``alias``, since nothing is next to it.
    """
    original = _existing(target)
    if alias is None and original.parent == original:
        raise ValueError("pass where to create the alias of {}: there's no folder around it".format(original))
    name = "{} alias".format(original.name or _display_name(original))
    if alias is None:
        destination = original.with_name(name)
    else:
        destination = Path(alias).expanduser().absolute()
        if destination.is_dir() and not destination.is_symlink():
            destination = destination / name
    if os.path.lexists(destination):
        raise FileExistsError(str(destination))
    if not destination.parent.is_dir():
        raise FileNotFoundError(str(destination.parent))
    with _objc.autorelease_pool():
        error = ctypes.c_void_p()
        bookmark = _objc.send(
            _objc.file_url(original),
            "bookmarkDataWithOptions:includingResourceValuesForKeys:relativeToURL:error:",
            _SUITABLE_FOR_BOOKMARK_FILE,
            None,
            None,
            ctypes.byref(error),
            argtypes=(NSUInteger, _objc.id, _objc.id, ctypes.c_void_p),
        )
        if not bookmark:
            _raise(error, "could not make an alias of {}".format(original))
        ok = _objc.send(
            _objc.cls("NSURL"),
            "writeBookmarkData:toURL:options:error:",
            bookmark,
            _objc.file_url(destination),
            _SUITABLE_FOR_BOOKMARK_FILE,
            ctypes.byref(error),
            argtypes=(_objc.id, _objc.id, NSUInteger, ctypes.c_void_p),
            restype=BOOL,
        )
        if not ok:
            _raise(error, "could not write the alias {}".format(destination))
    return destination


@dataclass(frozen=True)
class Event:
    """A change in a watched folder."""

    path: Path
    """The file or folder that changed, with symbolic links resolved (``/private/tmp/...`` for ``/tmp/...``)."""
    kind: str
    """
    ``'created'``, ``'modified'``, ``'deleted'`` or ``'renamed'`` (the new name of a moved or renamed item).

    ``'rescan'`` when macOS couldn't say what changed (it dropped events, or merged too many into one):
    ``path`` is then a folder whose contents may have changed in any way, to look through again.
    """
    is_dir: bool


# FSEventStreamEventFlags
_CREATED, _RENAMED, _IS_DIR = 0x100, 0x800, 0x20000
# MustScanSubDirs, UserDropped, KernelDropped: events were lost or coalesced, the folder must be read again.
_RESCAN = 0x1 | 0x2 | 0x4
_FILE_EVENTS, _NO_DEFER = 0x10, 0x2  # FSEventStreamCreateFlags: one event per file, the first one right away
_SINCE_NOW = 0xFFFFFFFFFFFFFFFF  # kFSEventStreamEventIdSinceNow
_LATENCY = 0.1  # seconds FSEvents gathers events for before calling back

_Callback = ctypes.CFUNCTYPE(
    None,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint64),
)


@lru_cache(maxsize=None)
def _core_services() -> ctypes.CDLL:
    services = framework("CoreServices")
    pointer = ctypes.c_void_p
    signatures = {
        "FSEventStreamCreate": (
            (pointer, _Callback, pointer, pointer, ctypes.c_uint64, ctypes.c_double, ctypes.c_uint32),
            pointer,
        ),
        "FSEventStreamScheduleWithRunLoop": ((pointer, pointer, pointer), None),
        "FSEventStreamStart": ((pointer,), ctypes.c_bool),
        "FSEventStreamStop": ((pointer,), None),
        "FSEventStreamInvalidate": ((pointer,), None),
        "FSEventStreamRelease": ((pointer,), None),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(services, name)
        function.argtypes = argtypes
        function.restype = restype
    return services


def _kind(path: Path, flags: int, seen: Set[Path]) -> str:
    """
    What happened to ``path``.

    FSEvents' flags pile up: a file's later changes still carry the
    "created" flag, and a rename flags both names. So a path that no longer
    exists was deleted (or moved away), and only the first sighting of a
    created path counts as its creation.
    """
    if not os.path.lexists(str(path)):
        seen.discard(path)
        return "deleted"
    first = path not in seen
    seen.add(path)
    if flags & _RENAMED and not flags & _CREATED:
        return "renamed"
    if flags & _CREATED and first:
        return "created"
    if flags & _RENAMED and first:
        return "renamed"
    return "modified"


def _matches(name: str, pattern: Union[str, Sequence[str], None]) -> bool:
    if pattern is None:
        return True
    patterns = [pattern] if isinstance(pattern, str) else pattern
    # Mac file systems ignore case, and so does the match.
    return any(fnmatch.fnmatchcase(name.casefold(), wanted.casefold()) for wanted in patterns)


def watch(
    path: PathLike,
    *,
    pattern: Union[str, Sequence[str], None] = None,
    recursive: bool = True,
    timeout: Optional[float] = None,
) -> Iterator[Event]:
    """
    Yield an :class:`Event` each time something changes in the folder ``path``, as it happens.

    ::

        for event in macos.finder.watch("~/Downloads"):
            if event.kind == "created" and event.path.suffix == ".pdf":
                print("new PDF:", event.path.name)

    It goes on until you ``break`` out of the loop, or ``timeout`` seconds
    pass. ``pattern`` keeps the files whose name matches it, such as
    ``"*.pdf"`` (or any of a list, ignoring case), and ``recursive=False``
    ignores what happens in subfolders. Writing a
    new file usually yields ``'created'`` and then ``'modified'``; saving
    over a file yields ``'modified'``. When macOS loses track (events dropped
    under heavy load), a ``'rescan'`` event names the folder to look through
    again. Uses FSEvents, like Spotlight and Time
    Machine: no polling, and no permission needed, except that the
    Desktop, Documents and Downloads folders ask for access the first time,
    like any access to them.
    """
    folder = Path(os.path.realpath(os.path.expanduser(str(path))))
    if not folder.is_dir():
        raise NotADirectoryError(str(folder))
    services, run_loop = _core_services(), _cf.lib()  # the run loop's functions are declared there
    if pattern is not None and not isinstance(pattern, str):
        # Kept as a tuple: checking a generator would use it up before the first event.
        try:
            pattern = tuple(pattern)
        except TypeError:
            pattern = (pattern,)  # type: ignore[assignment]
        if not all(isinstance(wanted, str) for wanted in pattern):
            raise TypeError("pattern must be a str or a list of str, not {!r}".format(pattern))
    pending: "collections.deque[Event]" = collections.deque()
    errors: List[Exception] = []
    seen: Set[Path] = set()

    def changed(stream: int, info: int, count: int, paths: int, flags: "ctypes._Pointer", ids: "ctypes._Pointer") -> None:
        try:
            names = ctypes.cast(paths, ctypes.POINTER(ctypes.c_char_p))
            for index in range(count):
                changed_path = Path(os.fsdecode(names[index]))
                if flags[index] & _RESCAN:
                    # Whatever the pattern: the files it would match may be among the lost events.
                    if changed_path != folder and folder not in changed_path.parents:
                        pending.append(Event(folder, "rescan", True))  # lost above the folder: all of it
                    elif recursive or changed_path == folder:
                        pending.append(Event(changed_path, "rescan", True))
                    continue
                if changed_path == folder or (not recursive and changed_path.parent != folder):
                    continue
                if not _matches(changed_path.name, pattern):
                    continue
                pending.append(Event(changed_path, _kind(changed_path, flags[index], seen), bool(flags[index] & _IS_DIR)))
        except Exception as error:  # an exception must not cross back into C: the loop below raises it
            errors.append(error)

    callback = _Callback(changed)  # kept alive for as long as the stream runs
    with _cf.owned(_cf.from_python([str(folder)])) as paths:
        stream = services.FSEventStreamCreate(None, callback, None, paths, _SINCE_NOW, _LATENCY, _FILE_EVENTS | _NO_DEFER)
    if not stream:
        raise MacOSError("could not watch {}".format(folder))
    mode = _cf.default_mode()
    services.FSEventStreamScheduleWithRunLoop(stream, run_loop.CFRunLoopGetCurrent(), mode)
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        if not services.FSEventStreamStart(stream):
            raise MacOSError("could not watch {}".format(folder))
        while True:
            while pending:
                yield pending.popleft()
            if errors:
                raise errors.pop(0)
            remaining = 0.1 if deadline is None else min(0.1, deadline - time.monotonic())
            if remaining <= 0:
                return
            run_loop.CFRunLoopRunInMode(mode, remaining, True)
    finally:
        services.FSEventStreamStop(stream)
        services.FSEventStreamInvalidate(stream)
        services.FSEventStreamRelease(stream)


def wait_for_change(
    path: PathLike,
    *,
    pattern: Union[str, Sequence[str], None] = None,
    recursive: bool = True,
    timeout: Optional[float] = None,
) -> Optional[Event]:
    """
    Wait until something changes in the folder ``path``, and return that :class:`Event`.

    Returns ``None`` if ``timeout`` seconds pass first. Handy to wait for a
    download or an export to show up::

        event = macos.finder.wait_for_change("~/Downloads", pattern="*.pdf", timeout=60)

    ``pattern`` and ``recursive`` work as in :func:`watch`. When macOS loses
    track of what changed (a ``'rescan'`` in :func:`watch`), the folder is
    looked through for a matching file made or changed since the wait began.
    """
    # Some disks keep file times to the second or two (FAT), and some systems a little behind
    # the clock: a file written just after the wait began may carry a time just before it.
    since = time.time() - _TIME_SLACK
    if pattern is not None and not isinstance(pattern, str):
        pattern = tuple(pattern)  # read twice: by watch() and by the look through the folder
    for event in watch(path, pattern=pattern, recursive=recursive, timeout=timeout):
        if event.kind != "rescan":
            return event
        found = _changed_since(event.path, since, pattern, recursive)
        if found is not None:
            return found
    return None


_TIME_SLACK = 2.0  # seconds


def _changed_since(folder: Path, since: float, pattern: Union[str, Sequence[str], None], recursive: bool) -> Optional[Event]:
    """A file in ``folder`` matching ``pattern``, made or changed at ``since`` or later, as an :class:`Event`; or ``None``."""
    for root, folders, files in os.walk(str(folder)):
        for name in files + folders:
            if not _matches(name, pattern):
                continue
            changed = Path(root) / name
            try:
                info = os.lstat(str(changed))
            except OSError:
                continue  # gone meanwhile
            if info.st_mtime >= since or info.st_ctime >= since:
                made = getattr(info, "st_birthtime", 0) >= since
                return Event(changed, "created" if made else "modified", name in folders)
        if not recursive:
            break
    return None


_SELECTION = """
on run argv
    tell application "Finder" to set picked to selection as alias list
    set out to ""
    repeat with item_ in picked
        set out to out & (POSIX path of item_) & (ASCII character 30)
    end repeat
    return out
end run
"""

_CURRENT_FOLDER = """
on run argv
    tell application "Finder"
        if (count of Finder windows) is 0 then return ""
        try
            return POSIX path of (target of front Finder window as alias)
        on error
            return ""
        end try
    end tell
end run
"""


def selection() -> List[Path]:
    """
    The files and folders selected in Finder, in the window in front (or on the Desktop).

    Handy for scripts that act on what you picked, from a hotkey or a Shortcut::

        for path in macos.finder.selection():
            macos.image.convert(path, path.with_suffix(".jpg"))

    Goes through AppleScript: the first time, macOS asks to allow the app
    running Python to control Finder.
    """
    output = applescript("Finder", _SELECTION).rstrip("\n")
    return [Path(item.rstrip("/") or "/") for item in output.split("\x1e") if item]


def current_folder() -> Optional[Path]:
    """
    The folder shown in Finder's window in front, or ``None`` with no window open.

    Places that aren't folders (Recents, AirDrop, a search) give ``None`` too.
    """
    output = applescript("Finder", _CURRENT_FOLDER).rstrip("\n")
    return Path(output.rstrip("/") or "/") if output else None


_FINDER = "com.apple.finder"


def restart() -> None:
    """Relaunch Finder, so it reads its settings again (the ``set_show_*`` functions do it for you)."""
    if restart_later("Finder", restart):
        return
    killall("Finder")  # macOS opens it again right away, with its windows (unless quit from its menu, see set_quit_menu)


def _setting(domain: str, key: str) -> bool:
    return bool(defaults.read(domain, key, default=False))


def _set(domain: str, key: str, on: bool) -> None:
    defaults.write(domain, key, bool(on))
    restart()


def show_hidden_files() -> bool:
    """Whether Finder shows hidden files (``.git``, ``.env``...), as ⌘⇧. toggles."""
    return _setting(_FINDER, "AppleShowAllFiles")


def set_show_hidden_files(on: bool = True) -> None:
    """Show hidden files in Finder, or hide them again. Relaunches Finder."""
    _set(_FINDER, "AppleShowAllFiles", on)


def show_extensions() -> bool:
    """Whether Finder shows every file name's extension (``.pdf``, ``.txt``...)."""
    return _setting("NSGlobalDomain", "AppleShowAllExtensions")


def set_show_extensions(on: bool = True) -> None:
    """Show every file name's extension in Finder, like Finder › Settings › Advanced. Relaunches Finder."""
    _set("NSGlobalDomain", "AppleShowAllExtensions", on)


def show_path_bar() -> bool:
    """Whether Finder windows show the path bar, the folders leading to the one shown."""
    return _setting(_FINDER, "ShowPathbar")


def set_show_path_bar(on: bool = True) -> None:
    """Show the path bar at the bottom of Finder windows, or hide it. Relaunches Finder."""
    _set(_FINDER, "ShowPathbar", on)


def show_status_bar() -> bool:
    """Whether Finder windows show the status bar, with the item count and the free space."""
    return _setting(_FINDER, "ShowStatusBar")


def set_show_status_bar(on: bool = True) -> None:
    """Show the status bar at the bottom of Finder windows, or hide it. Relaunches Finder."""
    _set(_FINDER, "ShowStatusBar", on)


def compress(path: PathLike, output: Optional[PathLike] = None) -> Path:
    """
    Zip a file or folder, like Finder's *Compress*, and return the ``.zip``.

    By default the archive goes next to it, as ``<name>.zip``. It keeps what
    plain zip tools lose: extended attributes, tags, resource forks and
    permissions. Uses the ``ditto`` command, as Finder does.
    """
    source = _existing(path)
    target = Path(output).expanduser().absolute() if output is not None else source.with_name(source.name + ".zip")
    if target.suffix.lower() != ".zip":
        raise ValueError("the archive must end in .zip, not {!r}".format(target.name))
    _run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(source), str(target)])
    return target


def extract(archive: PathLike, destination: Optional[PathLike] = None) -> Path:
    """
    Unzip an archive, like double-clicking it, into ``destination`` (by default, its folder); return ``destination``.

    Keeps the attributes and permissions :func:`compress` stores.
    """
    source = _existing(archive)
    target = Path(destination).expanduser().absolute() if destination is not None else source.parent
    target.mkdir(parents=True, exist_ok=True)
    _run(["ditto", "-x", "-k", str(source), str(target)])
    return target


def quick_look(path: PathLike) -> None:
    """
    Show a file in Quick Look, the preview Space opens in Finder, and return at once.

    The preview stays until the user closes it.
    """
    import subprocess

    source = _existing(path)
    require_macos()
    subprocess.Popen(
        ["qlmanage", "-p", str(source)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # outlives the script, as a preview opened from Finder does
    )


def show_desktop_icons() -> bool:
    """Whether the desktop shows its files and folders (and mounted disks)."""
    return _setting_default(_FINDER, "CreateDesktop", True)


def set_show_desktop_icons(on: bool = True) -> None:
    """
    Show the desktop's icons, or hide them all (``False``), for a clean screen in presentations and recordings.

    The files stay on the Desktop, in its folder. Relaunches Finder.
    """
    _set(_FINDER, "CreateDesktop", on)


def _setting_default(domain: str, key: str, default: bool) -> bool:
    return bool(defaults.read(domain, key, default=default))


_VIEWS = {"icons": "icnv", "list": "Nlsv", "columns": "clmv", "gallery": "glyv"}


def default_view() -> str:
    """How Finder shows folders that have no view of their own: ``'icons'``, ``'list'``, ``'columns'`` or ``'gallery'``."""
    code = defaults.read(_FINDER, "FXPreferredViewStyle", default="icnv")
    return next((view for view, found in _VIEWS.items() if found == code), "icons")


def set_default_view(view: str) -> None:
    """
    Show folders as ``'icons'``, a ``'list'``, ``'columns'`` or a ``'gallery'`` by default. Relaunches Finder.

    Folders already shown another way keep their own view.
    """
    if view not in _VIEWS:
        raise ValueError("view must be one of {}, not {!r}".format(", ".join(_VIEWS), view))
    defaults.write(_FINDER, "FXPreferredViewStyle", _VIEWS[view])
    restart()


_UF_HIDDEN = 0x8000  # stat.UF_HIDDEN: the flag chflags hidden sets


def show_library_folder() -> bool:
    """Whether your Library folder (``~/Library``) shows in Finder; macOS hides it."""
    require_macos()
    flags = getattr(os.stat(str(Path.home() / "Library")), "st_flags", 0)  # only BSD systems have file flags
    return not flags & _UF_HIDDEN


def set_show_library_folder(on: bool = True) -> None:
    """Show your Library folder in Finder, or hide it again, as ``chflags nohidden ~/Library`` does."""
    _run(["chflags", "nohidden" if on else "hidden", str(Path.home() / "Library")])


_NEW_WINDOW_TARGETS = {"PfHm": "~", "PfDe": "~/Desktop", "PfDo": "~/Documents"}


def new_window_folder() -> Path:
    """The folder a new Finder window (⌘N) opens."""
    target = defaults.read(_FINDER, "NewWindowTarget", default="PfHm")
    if target in _NEW_WINDOW_TARGETS:
        return Path(os.path.expanduser(_NEW_WINDOW_TARGETS[target]))
    url = defaults.read(_FINDER, "NewWindowTargetPath", default="")
    from urllib.parse import unquote, urlparse

    return Path(unquote(urlparse(url).path)).absolute() if url else Path.home()


def set_new_window_folder(folder: PathLike) -> None:
    """Open new Finder windows (⌘N) in ``folder``, such as ``"~/Downloads"``. Relaunches Finder."""
    from urllib.parse import quote

    target = _existing(folder)
    if not target.is_dir():
        raise NotADirectoryError(str(target))
    defaults.write(_FINDER, "NewWindowTarget", "PfLo")
    defaults.write(_FINDER, "NewWindowTargetPath", "file://{}/".format(quote(str(target))))
    restart()


_SCOPES = {"this_mac": "SCev", "current_folder": "SCcf", "previous": "SCsp"}


def search_scope() -> str:
    """Where a Finder search looks first: ``'this_mac'``, ``'current_folder'`` or ``'previous'`` (the last scope used)."""
    code = defaults.read(_FINDER, "FXDefaultSearchScope", default="SCev")
    return next((scope for scope, found in _SCOPES.items() if found == code), "this_mac")


def set_search_scope(scope: str) -> None:
    """
    Search the ``'current_folder'``, the whole Mac (``'this_mac'``), or the ``'previous'`` scope by default.

    Relaunches Finder.
    """
    if scope not in _SCOPES:
        raise ValueError("scope must be one of {}, not {!r}".format(", ".join(_SCOPES), scope))
    defaults.write(_FINDER, "FXDefaultSearchScope", _SCOPES[scope])
    restart()


def show_full_path_in_title() -> bool:
    """Whether Finder windows show the folder's full path in their title."""
    return _setting_default(_FINDER, "_FXShowPosixPathInTitle", False)


def set_show_full_path_in_title(on: bool = True) -> None:
    """Show the folder's full path (``/Users/alice/Projects``) in Finder windows' title. Relaunches Finder."""
    _set(_FINDER, "_FXShowPosixPathInTitle", on)


def folders_first() -> bool:
    """Whether folders come before files when windows are sorted by name."""
    return _setting_default(_FINDER, "_FXSortFoldersFirst", False)


def set_folders_first(on: bool = True) -> None:
    """Keep folders before files when sorting by name, in windows and on the desktop, or mix them."""
    defaults.write(_FINDER, "_FXSortFoldersFirstOnDesktop", bool(on))
    _set(_FINDER, "_FXSortFoldersFirst", on)


def extension_change_warning() -> bool:
    """Whether Finder asks before a file's extension is changed."""
    return _setting_default(_FINDER, "FXEnableExtensionChangeWarning", True)


def set_extension_change_warning(on: bool = True) -> None:
    """Ask before changing a file's extension, or rename it straight away (``False``)."""
    _set(_FINDER, "FXEnableExtensionChangeWarning", on)


def remove_old_trash_items() -> bool:
    """Whether items are deleted from the Trash after 30 days."""
    return _setting_default(_FINDER, "FXRemoveOldTrashItems", False)


def set_remove_old_trash_items(on: bool = True) -> None:
    """Delete items from the Trash after 30 days, or keep them until it's emptied."""
    _set(_FINDER, "FXRemoveOldTrashItems", on)


_DESKTOP_DRIVES = {
    "internal": ("ShowHardDrivesOnDesktop", False),
    "external": ("ShowExternalHardDrivesOnDesktop", True),
    "removable": ("ShowRemovableMediaOnDesktop", True),
    "servers": ("ShowMountedServersOnDesktop", False),
}


def drives_on_desktop() -> Dict[str, bool]:
    """
    Which disks show on the desktop: ``{"internal": False, "external": True, "removable": True, "servers": False}``.
    """
    return {kind: _setting_default(_FINDER, key, default) for kind, (key, default) in _DESKTOP_DRIVES.items()}


def set_show_drives_on_desktop(
    *,
    internal: Optional[bool] = None,
    external: Optional[bool] = None,
    removable: Optional[bool] = None,
    servers: Optional[bool] = None,
) -> None:
    """
    Show or hide each kind of disk on the desktop; the ones left out stay as they are.

    ::

        macos.finder.set_show_drives_on_desktop(external=False, servers=True)

    ``internal`` is the Mac's own disk, ``external`` the USB and Thunderbolt
    ones, ``removable`` CDs and the like, ``servers`` the network shares.
    """
    wanted = {"internal": internal, "external": external, "removable": removable, "servers": servers}
    if all(on is None for on in wanted.values()):
        raise ValueError("say which disks to show or hide: internal=, external=, removable= or servers=")
    for kind, on in wanted.items():
        if on is not None:
            defaults.write(_FINDER, _DESKTOP_DRIVES[kind][0], bool(on))
    restart()


def quit_menu() -> bool:
    """Whether Finder has a Quit item (⌘Q), so it can be closed like other apps."""
    return _setting_default(_FINDER, "QuitMenuItem", False)


def set_quit_menu(on: bool = True) -> None:
    """Add Quit Finder (⌘Q) to Finder's menu, or take it away. Quitting Finder also hides the desktop's icons."""
    _set(_FINDER, "QuitMenuItem", on)


# The desktop's sort orders, as Finder's arrangeBy names them.
_DESKTOP_SORTS = {
    None: "none",
    "snap_to_grid": "grid",
    "name": "name",
    "kind": "kind",
    "date_last_opened": "dateLastOpened",
    "date_added": "dateAdded",
    "date_modified": "dateModified",
    "date_created": "dateCreated",
    "size": "size",
    "tags": "label",
}


def _desktop_icons() -> Dict[str, Any]:
    view = defaults.read(_FINDER, "DesktopViewSettings", default={}) or {}
    return dict(view.get("IconViewSettings", {}))


def desktop_view() -> Dict[str, object]:
    """
    How the desktop shows its icons, as in its View › Show View Options.

    ``{"icon_size": 64, "grid_spacing": 54, "text_size": 12, "sort": None,
    "show_item_info": False, "labels_on_bottom": True}``; ``sort`` is
    ``None`` when the icons are placed freely.
    """
    icons = _desktop_icons()
    sorts = {value: name for name, value in _DESKTOP_SORTS.items()}
    return {
        "icon_size": int(float(icons.get("iconSize", 64))),
        "grid_spacing": int(float(icons.get("gridSpacing", 54))),
        "text_size": int(float(icons.get("textSize", 12))),
        "sort": sorts.get(icons.get("arrangeBy", "none")),
        "show_item_info": bool(icons.get("showItemInfo", False)),
        "labels_on_bottom": bool(icons.get("labelOnBottom", True)),
    }


def set_desktop_view(
    *,
    icon_size: Optional[int] = None,
    grid_spacing: Optional[int] = None,
    text_size: Optional[int] = None,
    sort: Union[str, None, bool] = False,
    show_item_info: Optional[bool] = None,
    labels_on_bottom: Optional[bool] = None,
) -> None:
    """
    Change how the desktop shows its icons; the options left out stay as they are.

    ::

        macos.finder.set_desktop_view(icon_size=48, grid_spacing=30, sort="kind")

    ``icon_size`` is from 16 to 128 points, ``grid_spacing`` from 1 to 100,
    and ``text_size``, the size of the names under the icons, from 10 to 16
    points. ``sort`` keeps them in order:
    ``"snap_to_grid"``, ``"name"``, ``"kind"``, ``"date_added"``,
    ``"date_modified"``, ``"date_created"``, ``"date_last_opened"``,
    ``"size"``, ``"tags"``, or ``None`` to place them freely.
    ``show_item_info`` adds a line under each name (a disk's free space, a
    folder's item count, an image's size), and ``labels_on_bottom=False``
    puts the names to the right of the icons instead of below. Relaunches Finder.
    """
    changes: Dict[str, object] = {}
    for name, value, low, high, key in (
        ("icon_size", icon_size, 16, 128, "iconSize"),
        ("grid_spacing", grid_spacing, 1, 100, "gridSpacing"),
        ("text_size", text_size, 10, 16, "textSize"),
    ):
        if value is not None:
            if not low <= value <= high:
                raise ValueError("{} must be from {} to {}, not {}".format(name, low, high, value))
            changes[key] = float(value)
    if sort is not False:
        if sort not in _DESKTOP_SORTS:
            names = ", ".join(name for name in _DESKTOP_SORTS if name)
            raise ValueError("sort must be one of {} or None, not {!r}".format(names, sort))
        changes["arrangeBy"] = _DESKTOP_SORTS[sort]
    if show_item_info is not None:
        changes["showItemInfo"] = bool(show_item_info)
    if labels_on_bottom is not None:
        changes["labelOnBottom"] = bool(labels_on_bottom)
    if not changes:
        raise ValueError("say what to change: icon_size=, grid_spacing=, text_size=, sort=, show_item_info= or labels_on_bottom=")
    view = dict(defaults.read(_FINDER, "DesktopViewSettings", default={}) or {})
    icons = dict(view.get("IconViewSettings", {}))
    icons.update(changes)
    view["IconViewSettings"] = icons
    defaults.write(_FINDER, "DesktopViewSettings", view)
    restart()


# --- Custom icons ---------------------------------------------------------------

_HAS_CUSTOM_ICON = 0x0400  # kHasCustomIcon, in the Finder flags of com.apple.FinderInfo


def _set_icon(target: Path, image: Optional[int]) -> None:
    framework("AppKit")
    workspace = _objc.send(_objc.cls("NSWorkspace"), "sharedWorkspace")
    ok = _objc.send(
        workspace,
        "setIcon:forFile:options:",
        image,
        _objc.nsstring(str(target)),
        0,
        argtypes=(_objc.id, _objc.id, NSUInteger),
        restype=BOOL,
    )
    if not ok:
        raise MacOSError("macOS refused to change the icon of {} (is it yours to change?)".format(target))


def set_icon(path: PathLike, image: PathLike) -> None:
    """
    Give ``path`` (a folder, a file or an app) a custom icon, like pasting one in Finder's Get Info.

    ::

        macos.finder.set_icon("~/Projects", "logo.png")                        # an image
        macos.finder.set_icon("~/Projects/app", "/Applications/Xcode.app")      # another item's icon

    ``image`` is an image file (PNG, JPEG, ICNS...), or any file, folder or
    app whose icon to copy. Finder and the Dock may take a moment to show it.
    An app in ``/Applications`` may need an administrator's rights.
    """
    target = _existing(path)
    source = _existing(image)
    with _objc.autorelease_pool():
        framework("AppKit")
        blank = _objc.send(_objc.cls("NSImage"), "alloc")
        picture = _objc.send(blank, "initWithContentsOfFile:", _objc.nsstring(str(source)), argtypes=(_objc.id,))
        if picture:
            _objc.send(picture, "autorelease")
        else:
            # Not an image: take the icon Finder shows for it.
            workspace = _objc.send(_objc.cls("NSWorkspace"), "sharedWorkspace")
            picture = _objc.send(workspace, "iconForFile:", _objc.nsstring(str(source)), argtypes=(_objc.id,))
        _set_icon(target, picture)


def remove_icon(path: PathLike) -> None:
    """Take away ``path``'s custom icon, so it shows its usual one again. Nothing happens if it had none."""
    target = _existing(path)
    with _objc.autorelease_pool():
        _set_icon(target, None)  # nil: the usual icon


def has_custom_icon(path: PathLike) -> bool:
    """
    Whether ``path`` has a custom icon, set with :func:`set_icon` or in Finder's Get Info.

    A symbolic link is asked about itself, not about what it points to, like
    :func:`macos.apps.is_quarantined`.
    """
    target = _existing(path)
    info = ctypes.create_string_buffer(32)  # FinderInfo's size
    # A symbolic link's own flags, as for the quarantine: not those of what it points to, which may be anywhere.
    size = _libc.lib().getxattr(os.fsencode(target), b"com.apple.FinderInfo", info, 32, 0, _libc.XATTR_NOFOLLOW)
    if size < 0:
        error = ctypes.get_errno()
        if error == _libc.ENOATTR:
            return False  # no Finder flags at all
        raise OSError(error, "can't read the Finder flags of {}: {}".format(target, os.strerror(error)))
    return size >= 10 and bool(int.from_bytes(info.raw[8:10], "big") & _HAS_CUSTOM_ICON)


def largest(
    folder: PathLike, count: int = 20, *, at_least: int = 1_000_000, timeout: Optional[float] = 60.0
) -> List[Tuple[Path, int]]:
    """
    The largest files in ``folder`` and its subfolders, the biggest first, with their size in bytes.

    ::

        for path, size in macos.finder.largest("~", count=10):
            print("{:>8.1f} MB  {}".format(size / 1e6, path))

    It asks Spotlight, which knows every file's size, so it's quick even for
    the whole home folder; ``at_least`` (1 MB by default) skips smaller
    files. The folders Spotlight leaves out, hidden ones and ``~/Library``,
    are walked instead when they're the folder or right under it, which is
    slower; hidden folders deeper in (a project's ``.git``) aren't searched.
    When Spotlight finds nothing there (it's off, or hasn't indexed that
    disk), the whole folder is walked file by file.

    Walking a big folder, a whole disk or a network share, can take very
    long: past ``timeout`` seconds of it, :class:`TimeoutError` is raised
    rather than an answer missing files. ``None`` walks for as long as it takes.
    """
    if count < 1:
        raise ValueError("count must be 1 or more, not {}".format(count))
    if timeout is not None and timeout <= 0:
        raise ValueError("timeout must be positive, or None, not {}".format(timeout))
    require_macos()  # before Spotlight: its "not supported" mustn't pass for "nothing indexed"
    root = _existing(folder)
    if not root.is_dir():
        raise NotADirectoryError(str(root))
    sizes: Dict[Path, int] = {}
    deadline = None if timeout is None else time.monotonic() + timeout

    def walk(top: Path) -> None:
        for current, _, files in os.walk(top):
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(
                    "looking through {} file by file took more than {:g} seconds (Spotlight hasn't indexed it); "
                    "pass a longer timeout, or None".format(top, timeout or 0)
                )
            for name in files:
                path = Path(current, name)
                try:
                    details = os.stat(path, follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISREG(details.st_mode) and details.st_size >= at_least:
                    sizes[path] = details.st_size

    if _unindexed(root):
        walk(root)  # Spotlight doesn't look in there at all
    else:
        paths: Iterable[Path]
        try:
            paths = spotlight.search("kMDItemFSSize >= {}".format(int(at_least)), folder=root)
        except MacOSError:
            paths = []
        for path in paths:
            try:
                details = os.stat(path, follow_symlinks=False)
            except OSError:
                continue  # gone since it was indexed
            if stat.S_ISREG(details.st_mode):
                sizes[Path(path)] = details.st_size
        if not sizes:
            walk(root)  # nothing indexed there (or nothing that big): look for ourselves
        else:
            # Spotlight leaves out hidden folders and ~/Library: walk those right under the folder too.
            try:
                children = [child for child in root.iterdir() if child.is_dir() and not child.is_symlink()]
            except OSError:
                children = []
            for child in children:
                if _unindexed(child):
                    walk(child)
    return sorted(sizes.items(), key=lambda item: (-item[1], str(item[0])))[:count]


def _unindexed(folder: Path) -> bool:
    """Whether Spotlight leaves ``folder`` out: a hidden one, or the user's Library, or inside one."""
    library = Path.home() / "Library"
    return any(part.startswith(".") for part in folder.parts[1:]) or folder == library or library in folder.parents
