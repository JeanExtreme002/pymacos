# -*- coding: utf-8 -*-

"""
List the printers, print files and follow the print queue.

::

    [p.description for p in macos.printer.printers()]    # ['Office LaserJet', 'Home Inkjet']
    macos.printer.default()                               # Printer(name='Office_LaserJet', ...)
    job = macos.printer.print_file("report.pdf", copies=2, two_sided=True)
    macos.printer.jobs()                                  # [PrintJob(id=12, title='report.pdf', state='processing', ...)]
    job.cancel()

Goes through CUPS, the printing system of macOS, like the ``lp`` and
``lpstat`` commands. No permission is needed; printing sends the file
straight to the printer, without a print dialog.
"""

import ctypes
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Union

from ._system import require_macos, run as _run
from .errors import MacOSError

__all__ = ["Printer", "PrintJob", "printers", "default", "set_default", "print_file", "jobs", "cancel"]


class _Option(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p), ("value", ctypes.c_char_p)]


class _Dest(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_char_p),
        ("instance", ctypes.c_char_p),
        ("is_default", ctypes.c_int),
        ("num_options", ctypes.c_int),
        ("options", ctypes.POINTER(_Option)),
    ]


class _Job(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_int),
        ("dest", ctypes.c_char_p),
        ("title", ctypes.c_char_p),
        ("user", ctypes.c_char_p),
        ("format", ctypes.c_char_p),
        ("state", ctypes.c_int),
        ("size", ctypes.c_int),
        ("priority", ctypes.c_int),
        ("completed_time", ctypes.c_long),
        ("creation_time", ctypes.c_long),
        ("processing_time", ctypes.c_long),
    ]


_PRINTER_STATES = {"3": "idle", "4": "printing", "5": "stopped"}
_JOB_STATES = {3: "pending", 4: "held", 5: "processing", 6: "stopped", 7: "canceled", 8: "aborted", 9: "completed"}
_ALL_JOBS, _ACTIVE_JOBS = -1, 0  # CUPS_WHICHJOBS_*


@lru_cache(maxsize=None)
def _cups() -> ctypes.CDLL:
    require_macos()
    cups = ctypes.CDLL("/usr/lib/libcups.2.dylib")  # in the system's shared cache
    dests = ctypes.POINTER(_Dest)
    cups.cupsGetDests.argtypes = (ctypes.POINTER(dests),)
    cups.cupsGetDests.restype = ctypes.c_int
    cups.cupsFreeDests.argtypes = (ctypes.c_int, dests)
    cups.cupsFreeDests.restype = None
    options = ctypes.POINTER(_Option)
    cups.cupsAddOption.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(options))
    cups.cupsAddOption.restype = ctypes.c_int
    cups.cupsFreeOptions.argtypes = (ctypes.c_int, options)
    cups.cupsFreeOptions.restype = None
    cups.cupsPrintFile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int, options)
    cups.cupsPrintFile.restype = ctypes.c_int
    job_list = ctypes.POINTER(_Job)
    cups.cupsGetJobs.argtypes = (ctypes.POINTER(job_list), ctypes.c_char_p, ctypes.c_int, ctypes.c_int)
    cups.cupsGetJobs.restype = ctypes.c_int
    cups.cupsFreeJobs.argtypes = (ctypes.c_int, job_list)
    cups.cupsFreeJobs.restype = None
    cups.cupsCancelJob.argtypes = (ctypes.c_char_p, ctypes.c_int)
    cups.cupsCancelJob.restype = ctypes.c_int
    cups.cupsLastErrorString.argtypes = ()
    cups.cupsLastErrorString.restype = ctypes.c_char_p
    return cups


def _text(value: Optional[bytes]) -> str:
    return value.decode("utf-8", "replace") if value else ""


def _error(cups: ctypes.CDLL) -> str:
    return _text(cups.cupsLastErrorString()) or "unknown error"


@dataclass(frozen=True)
class Printer:
    """A printer set up on this Mac."""

    name: str
    """The queue's name, which the other functions take, such as ``'Office_LaserJet'``."""
    description: str
    """The name System Settings shows, such as ``'Office LaserJet'``."""
    model: Optional[str]
    location: Optional[str]
    is_default: bool
    """Also ``True`` when the default is one of its saved sets of options (an ``lpoptions`` instance, ``Office/duplex``)."""
    state: Optional[str]
    """``'idle'``, ``'printing'`` or ``'stopped'``; ``None`` when the printer doesn't say (network printers often don't)."""


@dataclass(frozen=True)
class PrintJob:
    """A file sent to a printer."""

    id: int
    printer: str
    title: str
    user: str
    state: str
    """``'pending'``, ``'held'``, ``'processing'``, ``'stopped'``, ``'canceled'``, ``'aborted'`` or ``'completed'``."""
    size: int
    """In kilobytes."""
    created: Optional[datetime]

    def cancel(self) -> None:
        """Take the job out of the queue, or stop it if it's printing."""
        cancel(self)


def printers() -> List[Printer]:
    """The printers set up on this Mac, the default one first."""
    cups = _cups()
    dests = ctypes.POINTER(_Dest)()
    count = cups.cupsGetDests(ctypes.byref(dests))
    found = []
    try:
        # When the default is an instance, CUPS flags only the instance: its printer is the default.
        defaults = {_text(dests[index].name) for index in range(count) if dests[index].instance and dests[index].is_default}
        for index in range(count):
            dest = dests[index]
            if dest.instance:
                continue  # a saved set of options for a printer, not another printer
            options: Dict[str, str] = {
                _text(dest.options[number].name): _text(dest.options[number].value) for number in range(dest.num_options)
            }
            name = _text(dest.name)
            found.append(
                Printer(
                    name=name,
                    description=options.get("printer-info") or name,
                    model=options.get("printer-make-and-model") or None,
                    location=options.get("printer-location") or None,
                    is_default=bool(dest.is_default) or name in defaults,
                    state=_PRINTER_STATES.get(options.get("printer-state", "")),
                )
            )
    finally:
        cups.cupsFreeDests(count, dests)
    return sorted(found, key=lambda printer: not printer.is_default)


def default() -> Optional[Printer]:
    """
    The printer files go to when none is named; ``None`` when there's none.

    When the default is an ``lpoptions`` instance (``Office/duplex``), it's
    that instance's printer; jobs sent to it don't get the instance's options.
    """
    return next((printer for printer in printers() if printer.is_default), None)


def _name(printer: Union[None, str, Printer]) -> str:
    if isinstance(printer, Printer):
        return printer.name
    if printer is None:
        found = default()
        if found is None:
            raise MacOSError("there's no default printer: name one, or set it with macos.printer.set_default()")
        return found.name
    every = printers()
    if any(candidate.name == printer for candidate in every):
        return printer  # a queue's name is unique
    matches = [candidate.name for candidate in every if candidate.description == printer]
    if len(matches) > 1:
        raise ValueError(
            "several printers are named {!r}: use one of their queue names, {}".format(printer, ", ".join(matches))
        )
    if not matches:
        raise ValueError("no printer is named {!r}; see macos.printer.printers()".format(printer))
    return matches[0]


def set_default(printer: Union[str, Printer]) -> None:
    """Make ``printer`` (its name or its description) the one files go to when none is named, for you."""
    _run(["lpoptions", "-d", _name(printer)], timeout=30)  # it only writes a setting: never long


def print_file(
    path: Union[str, "os.PathLike[str]"],
    printer: Union[None, str, Printer] = None,
    *,
    copies: int = 1,
    pages: Optional[str] = None,
    two_sided: bool = False,
    black_and_white: bool = False,
    paper: Optional[str] = None,
    title: Optional[str] = None,
) -> PrintJob:
    """
    Print a file (PDF, image, text...) on ``printer``, the default one when not named, and return the job.

    ::

        macos.printer.print_file("invoice.pdf")
        macos.printer.print_file("slides.pdf", "Office LaserJet", pages="1-3,7", two_sided=True, copies=2)

    ``pages`` is a range like ``"1-3,7"``; ``paper`` a size such as
    ``"A4"`` or ``"Letter"``; ``title`` names the job in the queue (the
    file's name by default). It returns once the job is queued, not
    printed: follow it with :func:`jobs`.
    """
    file = Path(os.path.expanduser(os.fspath(path))).absolute()
    if not file.is_file():
        raise FileNotFoundError(str(file))
    if isinstance(copies, bool) or not isinstance(copies, int):
        raise TypeError("copies must be a whole number, not {!r}".format(copies))
    if copies < 1:
        raise ValueError("copies must be 1 or more, not {}".format(copies))
    name = _name(printer)
    wanted = {"copies": str(copies)}
    if pages:
        wanted["page-ranges"] = pages.replace(" ", "")
    if two_sided:
        wanted["sides"] = "two-sided-long-edge"
    if black_and_white:
        wanted["print-color-mode"] = "monochrome"
    if paper:
        wanted["media"] = paper
    cups = _cups()
    options = ctypes.POINTER(_Option)()
    count = 0
    for key, value in wanted.items():
        count = cups.cupsAddOption(key.encode(), value.encode(), count, ctypes.byref(options))
    try:
        job_id = cups.cupsPrintFile(name.encode(), os.fsencode(file), (title or file.name).encode(), count, options)
    finally:
        cups.cupsFreeOptions(count, options)
    if job_id <= 0:
        raise MacOSError("could not print {} on {}: {}".format(file.name, name, _error(cups)))
    for job in jobs(name, finished=True):
        if job.id == job_id:
            return job
    return PrintJob(id=job_id, printer=name, title=title or file.name, user="", state="pending", size=0, created=None)


def jobs(printer: Union[None, str, Printer] = None, *, finished: bool = False) -> List[PrintJob]:
    """
    The print jobs waiting or printing, on every printer or on ``printer``, oldest first.

    ``finished=True`` includes those done, canceled or aborted.
    """
    cups = _cups()
    name = None if printer is None else _name(printer).encode()
    found = ctypes.POINTER(_Job)()
    count = cups.cupsGetJobs(ctypes.byref(found), name, 0, _ALL_JOBS if finished else _ACTIVE_JOBS)
    if count < 0:
        raise MacOSError("could not read the print queue: {}".format(_error(cups)))
    try:
        listed = [
            PrintJob(
                id=found[index].id,
                printer=_text(found[index].dest),
                title=_text(found[index].title),
                user=_text(found[index].user),
                state=_JOB_STATES.get(found[index].state, "pending"),
                size=found[index].size,
                created=datetime.fromtimestamp(found[index].creation_time) if found[index].creation_time else None,
            )
            for index in range(count)
        ]
    finally:
        cups.cupsFreeJobs(count, found)
    return sorted(listed, key=lambda job: job.id)


def cancel(job: Union[int, PrintJob], printer: Union[None, str, Printer] = None) -> None:
    """
    Take a print job (a :class:`PrintJob` or its ``id``) out of the queue, or stop it if it's printing.

    An ``id`` is 1 or more: CUPS reads 0 as the job printing now and -1 as
    every job on the printer, so those raise :class:`ValueError` here.
    """
    if isinstance(job, PrintJob):
        job_id, name = job.id, job.printer
    else:
        if isinstance(job, bool):
            raise TypeError("a print job is a PrintJob or its id, not {!r}".format(job))
        job_id = int(job)
        if job_id < 1:
            raise ValueError("a print job id is 1 or more, not {}".format(job_id))
        name = _name(printer) if printer is not None else ""
    cups = _cups()
    if not cups.cupsCancelJob(name.encode() if name else None, job_id):
        raise MacOSError("could not cancel print job {}: {}".format(job_id, _error(cups)))
