"""Unit tests for :mod:`macos.schedule`. They run on any platform."""

import os
import plistlib
import sys
from pathlib import Path

import pytest

import macos


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(os, "getuid", lambda: 501, raising=False)
    script = tmp_path / "backup.py"
    script.write_text("print('hi')")
    return tmp_path


def _plist(home, name):
    return plistlib.loads((home / "Library" / "LaunchAgents" / "pymacos.{}.plist".format(name)).read_bytes())


def test_schedule_every(fake_run, home):
    job = macos.schedule.add("backup", home / "backup.py", every=3600, args=["--quiet"])

    plist = _plist(home, "backup")
    assert plist["Label"] == "pymacos.backup"
    assert plist["ProgramArguments"] == [sys.executable, str(home / "backup.py"), "--quiet"]
    assert plist["StartInterval"] == 3600 and plist["RunAtLoad"] is False
    assert plist["WorkingDirectory"] == str(home)
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == str(home / "Library/Logs/pymacos/backup.log")
    commands = [call["args"] for call in fake_run.calls]
    assert ["launchctl", "bootout", "gui/501/pymacos.backup"] in commands  # replacing a job unloads the old one
    assert ["launchctl", "bootstrap", "gui/501", str(home / "Library/LaunchAgents/pymacos.backup.plist")] in commands
    assert (job.name, job.every, job.at, job.args) == ("backup", 3600, (), ("--quiet",))


def test_schedule_at_times_and_weekdays(fake_run, home):
    job = macos.schedule.add("report", home / "backup.py", at=["9:00", "18:30"], weekdays=["Mon", "friday"])

    assert _plist(home, "report")["StartCalendarInterval"] == [
        {"Hour": 9, "Minute": 0, "Weekday": 1},
        {"Hour": 9, "Minute": 0, "Weekday": 5},
        {"Hour": 18, "Minute": 30, "Weekday": 1},
        {"Hour": 18, "Minute": 30, "Weekday": 5},
    ]
    assert (job.at, job.weekdays, job.every) == (("09:00", "18:30"), ("mon", "fri"), None)


def test_schedule_at_login_jobs_and_remove(fake_run, home):
    macos.schedule.add("hello", home / "backup.py", at_login=True, python=home / "venv/bin/python")
    macos.schedule.add("daily", home / "backup.py", at="07:15")

    assert _plist(home, "hello")["RunAtLoad"] is True
    assert _plist(home, "hello")["ProgramArguments"][0] == str(home / "venv/bin/python")
    assert [job.name for job in macos.schedule.jobs()] == ["daily", "hello"]
    assert macos.schedule.remove("hello") is True
    assert macos.schedule.remove("hello") is False
    assert macos.schedule.get("hello") is None
    macos.schedule.run_now("daily")
    assert fake_run.args == ["launchctl", "kickstart", "gui/501/pymacos.daily"]


def test_schedule_reads_the_job_state(fake_run, home):
    macos.schedule.add("backup", home / "backup.py", every=60)
    fake_run.stdout = '{\n\t"LastExitStatus" = 256;\n\t"PID" = 4242;\n\t"Label" = "pymacos.backup";\n};\n'

    job = macos.schedule.get("backup")

    assert job.running is True and job.last_exit_status == 256


def test_schedule_argument_checks(fake_run, home):
    script = home / "backup.py"
    checks = [
        (lambda: macos.schedule.add("bad name", script, every=60), "name must be"),
        (lambda: macos.schedule.add("x", script), "every=, at=, at_login=True, when_changed= or at_mount=True"),
        (lambda: macos.schedule.add("x", script, when_changed=[]), "at least one path"),
        (lambda: macos.schedule.add("x", script, every=60, at="09:00"), "either every or at"),
        (lambda: macos.schedule.add("x", script, every=0), "at least 1 second"),
        (lambda: macos.schedule.add("x", script, at="25:00"), "a time such as"),
        (lambda: macos.schedule.add("x", script, at=[]), "at least one time"),
        (lambda: macos.schedule.add("x", script, at="09:00", weekdays=["someday"]), "weekdays are"),
        (lambda: macos.schedule.add("x", script, every=60, weekdays=["mon"]), "only apply with at"),
        (lambda: macos.schedule.run_now("missing"), "no job named"),
    ]
    for call, message in checks:
        with pytest.raises(ValueError, match=message):
            call()
    with pytest.raises(FileNotFoundError):
        macos.schedule.add("x", home / "missing.py", every=60)
    assert not Path(home / "Library/LaunchAgents").exists() or not list(Path(home / "Library/LaunchAgents").iterdir())


def test_schedule_takes_timedelta_and_time(fake_run, home):
    import datetime

    macos.schedule.add("hourly", home / "backup.py", every=datetime.timedelta(minutes=90))
    macos.schedule.add("morning", home / "backup.py", at=[datetime.time(7, 5, 30), "19:00"])

    assert _plist(home, "hourly")["StartInterval"] == 5400
    assert _plist(home, "morning")["StartCalendarInterval"] == [{"Hour": 7, "Minute": 5}, {"Hour": 19, "Minute": 0}]


def test_schedule_pause_and_resume(fake_run, home):
    macos.schedule.add("backup", home / "backup.py", every=60)
    fake_run.calls.clear()

    macos.schedule.pause("backup")
    assert [call["args"][1] for call in fake_run.calls] == ["bootout", "disable"]
    assert fake_run.args == ["launchctl", "disable", "gui/501/pymacos.backup"]

    fake_run.stdout = '\tdisabled services = {\n\t\t"pymacos.backup" => disabled\n\t\t"pymacos.other" => enabled\n\t}\n'
    assert macos.schedule.get("backup").paused is True
    fake_run.calls.clear()
    macos.schedule.remove("backup")  # a paused job is enabled again, so its name can be reused
    assert ["launchctl", "enable", "gui/501/pymacos.backup"] in [call["args"] for call in fake_run.calls]

    fake_run.stdout = ""
    macos.schedule.add("backup", home / "backup.py", every=60)
    fake_run.calls.clear()
    macos.schedule.resume("backup")
    assert [call["args"][1] for call in fake_run.calls] == ["bootout", "enable", "bootstrap"]
    with pytest.raises(ValueError, match="no job named"):
        macos.schedule.pause("missing")


def test_schedule_remove_only_ignores_a_job_that_isnt_loaded(fake_run, home, monkeypatch):
    import subprocess

    from macos import _system

    macos.schedule.add("backup", home / "backup.py", every=60)
    answers = {"bootout": (3, "Boot-out failed: 3: No such process")}

    def launchctl(args, **kwargs):
        code, error = answers.get(args[1], (0, ""))
        return subprocess.CompletedProcess(args, code, "", error)

    monkeypatch.setattr(_system.subprocess, "run", launchctl)
    assert macos.schedule.remove("backup") is True  # not loaded: fine

    macos.schedule.add("backup", home / "backup.py", every=60)
    answers["bootout"] = (5, "Boot-out failed: 5: Input/output error")
    with pytest.raises(macos.CommandError):
        macos.schedule.remove("backup")
    assert macos.schedule.get("backup") is not None  # still managed, since it may still be loaded


def test_schedule_when_changed_and_at_mount(fake_run, home):
    job = macos.schedule.add("tidy", home / "backup.py", when_changed="~/Downloads")
    assert _plist(home, "tidy")["WatchPaths"] == [str(home / "Downloads")]
    assert "StartOnMount" not in _plist(home, "tidy") and "StartInterval" not in _plist(home, "tidy")
    assert job.when_changed == (home / "Downloads",) and job.at_mount is False

    job = macos.schedule.add("copy", home / "backup.py", at_mount=True, every=600, when_changed=[home / "a", "b"])
    plist = _plist(home, "copy")
    assert plist["StartOnMount"] is True and plist["StartInterval"] == 600
    assert plist["WatchPaths"] == [str(home / "a"), str(Path("b").absolute())]
    assert job.at_mount is True and job.every == 600 and len(job.when_changed) == 2


@pytest.mark.parametrize("name", ["backup\n", "back up", "", "-x"])
def test_schedule_rejects_a_name_with_a_trailing_newline(fake_run, home, name):
    with pytest.raises(ValueError, match="name must be"):
        macos.schedule.add(name, home / "backup.py", every=60)


def test_schedule_rejects_a_time_with_a_trailing_newline(fake_run, home):
    with pytest.raises(ValueError, match="a time such as"):
        macos.schedule.add("x", home / "backup.py", at="09:00\n9")


def _failing_bootstrap(monkeypatch, fake_run, *, fail=True):
    """
    Record launchctl's commands; with ``fail``, the first bootstrap (the new job's) fails.

    Without it, every command succeeds: for the tests where something else
    fails before the new job is bootstrapped, so the old job's own bootstrap,
    when it's put back, must work.
    """
    import subprocess

    from macos import _system

    calls = []

    def launchctl(args, **kwargs):
        calls.append(list(args))
        if fail and args[1] == "bootstrap" and len([call for call in calls if call[1] == "bootstrap"]) == 1:
            return subprocess.CompletedProcess(args, 5, "", "Bootstrap failed: 5: Input/output error")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(_system.subprocess, "run", launchctl)
    return calls


def test_schedule_add_removes_its_plist_when_bootstrap_fails(fake_run, home, monkeypatch):
    calls = _failing_bootstrap(monkeypatch, fake_run)

    with pytest.raises(macos.errors.CommandError, match="Bootstrap failed"):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert not (home / "Library/LaunchAgents/pymacos.backup.plist").exists()  # nothing left for the next login
    assert [call[1] for call in calls if call[1] == "bootstrap"] == ["bootstrap"]


def test_schedule_add_restores_the_replaced_job_when_bootstrap_fails(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=3600)
    calls = _failing_bootstrap(monkeypatch, fake_run)

    with pytest.raises(macos.errors.CommandError):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert _plist(home, "backup")["StartInterval"] == 3600  # the old job is back...
    path = str(home / "Library/LaunchAgents/pymacos.backup.plist")
    assert calls[-1] == ["launchctl", "bootstrap", "gui/501", path]  # ...and loaded again


def test_schedule_add_restores_the_replaced_job_when_writing_the_new_plist_fails(fake_run, home, monkeypatch):
    from pathlib import Path

    macos.schedule.add("backup", home / "backup.py", every=3600)
    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    calls = _failing_bootstrap(monkeypatch, fake_run, fail=False)  # the old job's bootstrap must succeed
    write_bytes = Path.write_bytes

    def disk_full(self, data):
        if self == path and b"<integer>60</integer>" in data:  # the new job's plist, not the old one put back
            write_bytes(self, data[:20])  # a partial write
            raise OSError(28, "No space left on device", str(self))
        return write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", disk_full)

    with pytest.raises(OSError, match="No space left"):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert _plist(home, "backup")["StartInterval"] == 3600  # the old job is back, not the partial plist...
    bootstraps = [call for call in calls if call[1] == "bootstrap"]
    assert bootstraps == [["launchctl", "bootstrap", "gui/501", str(path)]]  # ...loaded again: the only bootstrap


def test_schedule_add_restores_the_replaced_job_when_removing_it_fails(fake_run, home, monkeypatch):
    from pathlib import Path

    macos.schedule.add("backup", home / "backup.py", every=3600)
    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    calls = _failing_bootstrap(monkeypatch, fake_run, fail=False)  # the old job's bootstrap must succeed
    unlink = Path.unlink

    def refused(self, *args, **kwargs):
        if self == path:
            raise PermissionError(13, "Permission denied", str(self))  # after the old job was unloaded
        return unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refused)

    with pytest.raises(PermissionError):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert ["launchctl", "bootout", "gui/501/pymacos.backup"] in calls  # it was unloaded...
    bootstraps = [call for call in calls if call[1] == "bootstrap"]
    assert bootstraps == [["launchctl", "bootstrap", "gui/501", str(path)]]  # ...and loaded again: the only bootstrap
    assert _plist(home, "backup")["StartInterval"] == 3600


def test_schedule_add_removes_a_partial_plist_when_there_was_no_job(fake_run, home, monkeypatch):
    from pathlib import Path

    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    write_bytes = Path.write_bytes

    def disk_full(self, data):
        write_bytes(self, data[:20])
        raise OSError(28, "No space left on device", str(self))

    monkeypatch.setattr(Path, "write_bytes", disk_full)

    with pytest.raises(OSError, match="No space left"):
        macos.schedule.add("backup", home / "backup.py", every=60)
    assert not path.exists()


def test_schedule_add_leaves_a_job_whose_plist_it_cant_read(fake_run, home, monkeypatch):
    from pathlib import Path

    macos.schedule.add("backup", home / "backup.py", every=3600)
    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    calls = _failing_bootstrap(monkeypatch, fake_run)
    read_bytes = Path.read_bytes

    def unreadable(self):
        if self == path:
            raise PermissionError(13, "Permission denied", str(self))
        return read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    with pytest.raises(PermissionError):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert calls == []  # not unloaded, nor replaced: without a copy, it couldn't be put back
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert _plist(home, "backup")["StartInterval"] == 3600


def test_schedule_add_keeps_a_replaced_paused_job_paused_when_bootstrap_fails(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=3600)
    calls = _failing_bootstrap(monkeypatch, fake_run)
    monkeypatch.setattr(macos.schedule, "_paused", lambda: ["backup"])

    with pytest.raises(macos.errors.CommandError):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert _plist(home, "backup")["StartInterval"] == 3600
    assert calls[-1] == ["launchctl", "disable", "gui/501/pymacos.backup"]
