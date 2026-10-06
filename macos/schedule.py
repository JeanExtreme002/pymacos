# -*- coding: utf-8 -*-

"""
Run Python scripts on a schedule, at login, when a folder changes or when a disk
is plugged in, with launchd: the Mac's cron.

::

    macos.schedule.add("backup", "~/scripts/backup.py", every=3600)       # every hour
    macos.schedule.add("report", "report.py", at="09:00")                  # every day at 9
    macos.schedule.add("sync", "sync.py", at="18:30", weekdays=["mon", "fri"])
    macos.schedule.add("hello", "hello.py", at_login=True)
    macos.schedule.add("tidy", "tidy.py", when_changed="~/Downloads")      # a file arrives
    macos.schedule.add("copy", "copy.py", at_mount=True)                   # a disk is plugged in

    macos.schedule.jobs()          # [Job(name='backup', every=3600, ...), ...]
    macos.schedule.run_now("backup")
    macos.schedule.pause("backup")   # and resume("backup")
    macos.schedule.remove("backup")

Jobs are launch agents (``~/Library/LaunchAgents/pymacos.<name>.plist``):
they keep running after your script ends and after a restart, while you're
logged in. A job missed while the Mac slept runs when it wakes up.
"""

import datetime
import os
import plistlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from ._system import run as _run, require_macos
from .errors import CommandError

__all__ = ["Job", "add", "remove", "jobs", "get", "run_now", "pause", "resume"]

PathLike = Union[str, "os.PathLike[str]"]

_PREFIX = "pymacos."
# Checked with fullmatch: ``$`` alone also matches before a trailing newline,
# which would let "backup\n" through into a launchd label and a file name.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
_WEEKDAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # launchd counts from Sunday = 0


@dataclass(frozen=True)
class Job:
    """A scheduled script."""

    name: str
    script: Path
    args: Tuple[str, ...]
    every: Optional[int]
    """Seconds between runs, for jobs added with ``every``."""
    at: Tuple[str, ...]
    """The times of day (``'09:00'``...) for jobs added with ``at``."""
    weekdays: Tuple[str, ...]
    """The days ``at`` applies to (``'mon'``...); empty for every day."""
    at_login: bool
    when_changed: Tuple[Path, ...]
    """The files or folders whose changes run it, for jobs added with ``when_changed``."""
    at_mount: bool
    """Whether mounting a disk runs it."""
    paused: bool
    """Whether :func:`pause` stopped it."""
    log: Path
    """Where the script's output and errors go."""
    running: bool
    """Whether the script is running right now."""
    last_exit_status: Optional[int]
    """How the last run ended (0 is success), or ``None`` before the first run."""


def _agents() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _plist(name: str) -> Path:
    return _agents() / "{}{}.plist".format(_PREFIX, name)


def _log(name: str) -> Path:
    return Path.home() / "Library" / "Logs" / "pymacos" / "{}.log".format(name)


def _domain() -> str:
    return "gui/{}".format(os.getuid())


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("name must be letters, digits, '.', '_' or '-', not {!r}".format(name))


Moment = Union[str, datetime.time]


def _times(at: Union[Moment, Sequence[Moment], None]) -> List[Tuple[int, int]]:
    if at is None:
        return []
    found = []
    for moment in [at] if isinstance(at, (str, datetime.time)) else list(at):
        if isinstance(moment, datetime.time):
            found.append((moment.hour, moment.minute))
            continue
        text = moment
        match = _TIME.fullmatch(text.strip())
        if not match:
            raise ValueError("at must be a time such as '09:00' or '18:30', not {!r}".format(text))
        found.append((int(match.group(1)), int(match.group(2))))
    if not found:
        raise ValueError("at needs at least one time")
    return found


def _watched(when_changed: Union[PathLike, Sequence[PathLike], None]) -> List[str]:
    if when_changed is None:
        return []
    paths = [when_changed] if isinstance(when_changed, (str, os.PathLike)) else list(when_changed)
    if not paths:
        raise ValueError("when_changed needs at least one path")
    return [str(Path(path).expanduser().absolute()) for path in paths]


def _days(weekdays: Optional[Sequence[str]]) -> List[int]:
    if not weekdays:
        return []
    days = []
    for day in weekdays:
        short = day.strip().lower()[:3]
        if short not in _WEEKDAYS:
            raise ValueError("weekdays are 'mon', 'tue', 'wed', 'thu', 'fri', 'sat' or 'sun', not {!r}".format(day))
        days.append(_WEEKDAYS.index(short))
    return days


def add(
    name: str,
    script: PathLike,
    *,
    every: Union[float, datetime.timedelta, None] = None,
    at: Union[Moment, Sequence[Moment], None] = None,
    weekdays: Optional[Sequence[str]] = None,
    at_login: bool = False,
    when_changed: Union[PathLike, Sequence[PathLike], None] = None,
    at_mount: bool = False,
    args: Sequence[str] = (),
    python: Optional[PathLike] = None,
) -> Job:
    """
    Run the Python ``script`` on a schedule, from now on, and return the :class:`Job`.

    - ``every``: seconds between runs, or a :class:`~datetime.timedelta`.
    - ``at``: a time of day, ``"09:00"`` or a :class:`~datetime.time`, or
      several, ``["09:00", "18:00"]``; with ``weekdays`` (``["mon", "fri"]``),
      only on those days. Seconds are ignored: launchd counts minutes.
      ``every`` and ``at`` can't go together, and ``weekdays`` needs ``at``.
    - ``at_login``: run it each time you log in, and once right away.
    - ``when_changed``: a file or folder, or several, to watch: the script
      runs when one changes, and in a folder, when a file is added, removed
      or renamed there (not deeper). Changes made while it runs, or a few
      seconds apart, lead to one more run, not one each; the script isn't
      told what changed, so it looks at the folder itself. A path that
      doesn't exist yet counts once it's created. launchd may also run it
      once as the job is added.
    - ``at_mount``: run it each time a disk is mounted: an external drive, a
      USB stick, a disk image, a network share.

    ``when_changed`` and ``at_mount`` combine with the others:
    ``every=3600, when_changed="~/Inbox"`` runs hourly and on changes.

    It runs with this Python (``python=`` picks another, such as a virtual
    environment's), in the script's folder, with ``args`` as its
    arguments; its output goes to :attr:`Job.log`. Adding a name again
    replaces that job; if launchd refuses the new one, the old one is put
    back and the error raised. macOS shows a "Background Items Added" notification
    the first time, and lists the job in System Settings › General › Login
    Items & Extensions.

    The script runs outside your terminal, so it doesn't get the terminal's
    permissions (Full Disk Access, Screen Recording...): macOS asks for
    them again, for Python itself.
    """
    _check_name(name)
    if isinstance(every, datetime.timedelta):
        every = every.total_seconds()
    if every is not None and at is not None:
        raise ValueError("use either every or at, not both")
    if every is not None and every < 1:
        raise ValueError("every must be at least 1 second, not {}".format(every))
    if weekdays and at is None:
        raise ValueError("weekdays only apply with at")
    times, days = _times(at), _days(weekdays)
    watched = _watched(when_changed)
    if every is None and not times and not at_login and not watched and not at_mount:
        raise ValueError("say when to run it: every=, at=, at_login=True, when_changed= or at_mount=True")
    require_macos()
    source = Path(script).expanduser().absolute()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    interpreter = str(Path(python).expanduser().absolute()) if python is not None else sys.executable
    log = _log(name)
    log.parent.mkdir(parents=True, exist_ok=True)
    job = {
        "Label": _PREFIX + name,
        "ProgramArguments": [interpreter, str(source), *[str(arg) for arg in args]],
        "WorkingDirectory": str(source.parent),
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        # launchd's PATH is minimal: keep the caller's, so the script finds the same commands.
        "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"), "PYTHONUNBUFFERED": "1"},
        "RunAtLoad": bool(at_login),
    }
    if every is not None:
        job["StartInterval"] = int(every)
    if times:
        moments = [{"Hour": hour, "Minute": minute} for hour, minute in times]
        job["StartCalendarInterval"] = [dict(moment, Weekday=day) for moment in moments for day in days] if days else moments
    if watched:
        job["WatchPaths"] = watched
    if at_mount:
        job["StartOnMount"] = True
    path = _plist(name)
    # Replacing a job: keep the old plist's bytes, so a failed bootstrap of
    # the new one can put the old job back rather than leave neither (and a
    # half-installed plist launchd would pick up at the next login). One that
    # can't be read raises here, before the old job is touched.
    previous: Optional[bytes] = path.read_bytes() if path.exists() else None
    was_paused = previous is not None and name in _paused()
    plist = plistlib.dumps(job)  # before anything changes: a value it can't hold raises here
    try:
        # Removing the old job can fail after unloading it, and writing the new
        # plist (a full disk): those also put the old job back.
        remove(name)  # unload the old one first (and forget it was paused)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(plist)
        _run(["launchctl", "bootstrap", _domain(), str(path)])
    except BaseException:
        _restore(name, path, previous, was_paused)
        raise
    found = get(name)
    assert found is not None
    return found


def remove(name: str) -> bool:
    """Stop and delete the job ``name`` (and a run in progress); return whether there was one. Its log stays."""
    _check_name(name)
    require_macos()
    path = _plist(name)
    _bootout(name)
    if name in _paused():
        _run(["launchctl", "enable", _target(name)])  # a paused job's name is free again
    if path.exists():
        path.unlink()
        return True
    return False


def _restore(name: str, path: Path, previous: Optional[bytes], was_paused: bool) -> None:
    """
    Undo a failed :func:`add`: delete the new plist (if it got written), and put back the job it replaced, if any.

    Best effort: the caller re-raises the error that made it fail, which
    matters more than a failure here.
    """
    try:
        _bootout(name)  # in case launchd half-loaded it
    except Exception:
        pass
    try:
        if previous is None:
            path.unlink(missing_ok=True)
            return
        try:
            unchanged = path.read_bytes() == previous  # removing it failed: it's still there, as it was
        except OSError:
            unchanged = False
        if not unchanged:
            path.write_bytes(previous)  # skipped otherwise: a read-only plist would refuse, and keep it unloaded
        if was_paused:
            _run(["launchctl", "disable", _target(name)])  # a paused job stays unloaded
        else:
            _run(["launchctl", "bootstrap", _domain(), str(path)])
    except Exception:
        pass


def _target(name: str) -> str:
    return "{}/{}{}".format(_domain(), _PREFIX, name)


_NOT_LOADED = 3  # launchctl bootout: "No such process"


def _bootout(name: str) -> None:
    """Unload the job (stopping a run in progress); fine if it isn't loaded, an error otherwise."""
    try:
        _run(["launchctl", "bootout", _target(name)])
    except CommandError as error:
        if error.returncode != _NOT_LOADED:
            raise


def _paused() -> List[str]:
    """The names of the paused jobs, from ``launchctl print-disabled``."""
    try:
        output = _run(["launchctl", "print-disabled", _domain()])
    except CommandError:
        return []
    return re.findall(r'"{}([^"]+)"\s*=>\s*(?:disabled|true)'.format(re.escape(_PREFIX)), output)


def _state(name: str) -> Tuple[bool, Optional[int]]:
    """Whether the job is running, and its last exit status, from ``launchctl list``."""
    try:
        output = _run(["launchctl", "list", _PREFIX + name])
    except CommandError:
        return False, None
    pid = re.search(r'"PID"\s*=\s*(\d+);', output)
    status = re.search(r'"LastExitStatus"\s*=\s*(-?\d+);', output)
    return bool(pid), int(status.group(1)) if status else None


def _job(path: Path, paused: Sequence[str]) -> Optional[Job]:
    try:
        data = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    name = str(data.get("Label", ""))[len(_PREFIX):]
    arguments = list(data.get("ProgramArguments", []))
    calendar = data.get("StartCalendarInterval") or []
    if isinstance(calendar, dict):
        calendar = [calendar]
    times = tuple(dict.fromkeys("{:02}:{:02}".format(entry.get("Hour", 0), entry.get("Minute", 0)) for entry in calendar))
    days = tuple(dict.fromkeys(_WEEKDAYS[entry["Weekday"] % 7] for entry in calendar if "Weekday" in entry))
    running, status = _state(name)
    return Job(
        name=name,
        script=Path(arguments[1]) if len(arguments) > 1 else Path(),
        args=tuple(arguments[2:]),
        every=data.get("StartInterval"),
        at=times,
        weekdays=days,
        at_login=bool(data.get("RunAtLoad")),
        when_changed=tuple(Path(path) for path in data.get("WatchPaths") or [] if isinstance(path, str)),
        at_mount=bool(data.get("StartOnMount")),
        paused=name in paused,
        log=Path(data.get("StandardOutPath", str(_log(name)))),
        running=running,
        last_exit_status=status,
    )


def jobs() -> List[Job]:
    """The jobs added with :func:`add`, by name."""
    require_macos()
    paused = _paused()
    found = [_job(path, paused) for path in sorted(_agents().glob(_PREFIX + "*.plist"))]
    return [job for job in found if job is not None]


def get(name: str) -> Optional[Job]:
    """The job ``name``, or ``None``."""
    _check_name(name)
    require_macos()
    path = _plist(name)
    return _job(path, _paused()) if path.exists() else None


def run_now(name: str) -> None:
    """Start the job ``name`` right away, besides its schedule. Does nothing if it's already running."""
    _existing_job(name)
    _run(["launchctl", "kickstart", _target(name)])


def pause(name: str) -> None:
    """
    Stop the job ``name`` from running on its schedule, without deleting it; :func:`resume` restarts it.

    It stays paused after a restart. A run in progress is stopped too.
    """
    _existing_job(name)
    _bootout(name)
    _run(["launchctl", "disable", _target(name)])


def resume(name: str) -> None:
    """Put a job paused with :func:`pause` back on its schedule (with ``at_login``, it also runs now)."""
    path = _existing_job(name)
    _bootout(name)  # resuming a job that isn't paused: reload it
    _run(["launchctl", "enable", _target(name)])
    _run(["launchctl", "bootstrap", _domain(), str(path)])


def _existing_job(name: str) -> Path:
    _check_name(name)
    require_macos()
    path = _plist(name)
    if not path.exists():
        raise ValueError("no job named {!r}".format(name))
    return path
