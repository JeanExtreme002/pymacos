# -*- coding: utf-8 -*-

"""
Start Time Machine backups, follow them, and choose what they leave out.

::

    macos.time_machine.destinations()     # ['Backup Disk']
    macos.time_machine.backup_now()
    macos.time_machine.is_backing_up()    # True
    macos.time_machine.progress()         # 0.42
    macos.time_machine.last_backup()      # datetime.datetime(2026, 9, 28, 23, 10, 4)

    macos.time_machine.exclude("~/code/app/node_modules")
    macos.time_machine.is_excluded("~/code/app/node_modules")   # True

Goes through the ``tmutil`` command that ships with macOS. Reading the last
backup needs its disk to be connected, and may need Full Disk Access for the
app running Python.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from ._system import require_macos, run as _run
from .errors import CommandError, MacOSError, PermissionDeniedError

__all__ = [
    "destinations",
    "backup_now",
    "stop_backup",
    "is_backing_up",
    "progress",
    "last_backup",
    "exclude",
    "include",
    "is_excluded",
]

PathLike = Union[str, "os.PathLike[str]"]

_BACKUP_NAME = re.compile(r"(\d{4}-\d{2}-\d{2}-\d{6})")


def destinations() -> List[str]:
    """The names of the disks Time Machine backs up to; ``[]`` when none is set up."""
    require_macos()
    try:
        output = _run(["tmutil", "destinationinfo"])
    except CommandError as error:
        if "No destinations configured" in error.stderr:
            return []
        raise
    return [match.strip() for match in re.findall(r"^Name\s*:\s*(.+)$", output, re.M)]


def backup_now(*, wait: bool = False) -> None:
    """
    Start a backup, like *Back Up Now* in the Time Machine menu.

    Returns at once, unless ``wait=True``: then it returns when the backup is done.
    """
    if not destinations():
        raise MacOSError("Time Machine has no backup disk: set one up in System Settings › General › Time Machine")
    _run(["tmutil", "startbackup", *(["--block"] if wait else [])])


def stop_backup() -> None:
    """Stop the backup in progress, like *Skip This Backup*."""
    require_macos()
    _run(["tmutil", "stopbackup"])


def _status() -> str:
    require_macos()
    return _run(["tmutil", "status"])


def is_backing_up() -> bool:
    """Whether a backup is in progress."""
    return bool(re.search(r"\bRunning\s*=\s*1\s*;", _status()))


def progress() -> Optional[float]:
    """How far the backup in progress is, from 0.0 to 1.0; ``None`` when none is, or while it's getting ready."""
    status = _status()
    if not re.search(r"\bRunning\s*=\s*1\s*;", status):
        return None
    found = re.search(r'\bPercent\s*=\s*"?(-?[0-9.]+)"?\s*;', status)
    if not found or float(found.group(1)) < 0:
        return None
    return min(1.0, float(found.group(1)))


# What tmutil says when the app running Python lacks Full Disk Access: "tmutil:
# latestbackup requires Full Disk Access privileges", or the system's EPERM text.
_NO_ACCESS = ("Full Disk Access", "Operation not permitted")


def _check_access(text: str) -> None:
    if any(sign in text for sign in _NO_ACCESS):
        raise PermissionDeniedError(
            "Time Machine's backups need Full Disk Access: allow the app running Python (your terminal or IDE) "
            "in System Settings › Privacy & Security › Full Disk Access"
        )


def last_backup() -> Optional[datetime]:
    """
    When the latest backup was made, or ``None`` (no backup yet, or its disk isn't connected).

    Without Full Disk Access for the app running Python, raises
    :class:`~macos.errors.PermissionDeniedError` rather than pass for "no backup".
    """
    require_macos()
    try:
        output = _run(["tmutil", "latestbackup"])
    except CommandError as error:
        _check_access(error.stderr)
        return None  # no backup yet, no backup disk set up, or it isn't connected
    # tmutil prints the backup's path, named after its date; its errors come with a success status.
    _check_access(output)
    found = _BACKUP_NAME.findall(output)
    return datetime.strptime(found[-1], "%Y-%m-%d-%H%M%S") if found else None


def _existing(path: PathLike) -> str:
    require_macos()
    found = Path(path).expanduser().absolute()
    if not found.exists():
        raise FileNotFoundError(str(found))
    return str(found)


def exclude(path: PathLike) -> None:
    """
    Leave a file or folder out of the Time Machine backups, from the next one on.

    Handy for what can be downloaded or rebuilt again (``node_modules``,
    virtual environments, caches, virtual machines), which makes backups
    big and slow. The choice travels with the file: it stays when the file
    is moved or renamed. It doesn't need an administrator password, but it
    isn't listed in System Settings' *Exclude from Backups* list either.
    Copies made before stay on the backup disk.
    """
    _run(["tmutil", "addexclusion", _existing(path)])


def include(path: PathLike) -> None:
    """
    Back a file or folder up again, after :func:`exclude`.

    Nothing to do when it isn't excluded. Doesn't undo an exclusion made in
    System Settings or by macOS itself: see :func:`is_excluded`.
    """
    _run(["tmutil", "removeexclusion", _existing(path)])


def is_excluded(path: PathLike) -> bool:
    """
    Whether Time Machine leaves this file or folder out, for any reason:
    :func:`exclude`, the list in System Settings, or macOS itself (caches and
    temporary files). A file inside an excluded folder counts as excluded.
    """
    return _run(["tmutil", "isexcluded", _existing(path)]).lstrip().startswith("[Excluded]")
