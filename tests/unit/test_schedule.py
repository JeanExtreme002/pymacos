"""Unit tests for :mod:`macos.schedule`. They run on any platform."""

import os
import plistlib
import sys
import warnings
from pathlib import Path

import pytest

import macos


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(os, "getuid", lambda: 501, raising=False)
    script = tmp_path / "backup.py"
    script.write_text("print('hi')")
    script.chmod(0o644)  # only yours, whatever the umask: no warning about other users
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
    (home / "venv/bin").mkdir(parents=True)
    (home / "venv/bin/python").write_text("")
    (home / "venv/bin/python").chmod(0o755)
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

    # launchctl list <label> prints the wait status: 256 is an exit with 1.
    assert job.running is True and job.last_exit_status == 1
    fake_run.stdout = '{\n\t"LastExitStatus" = 9;\n\t"Label" = "pymacos.backup";\n};\n'
    assert macos.schedule.get("backup").last_exit_status == -9  # killed by SIGKILL, as the table form says
    fake_run.stdout = '{\n\t"LastExitStatus" = 0;\n\t"Label" = "pymacos.backup";\n};\n'
    assert macos.schedule.get("backup").last_exit_status == 0
    fake_run.stdout = '{\n\t"LastExitStatus" = -1;\n\t"Label" = "pymacos.backup";\n};\n'
    assert macos.schedule.get("backup").last_exit_status == -1  # not a wait status: as it is


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
    # Asked whether it's paused already, then disabled first: see the tests below.
    assert [call["args"][1] for call in fake_run.calls] == ["print-disabled", "disable", "bootout"]
    assert fake_run.args == ["launchctl", "bootout", "gui/501/pymacos.backup"]

    fake_run.stdout = '\tdisabled services = {\n\t\t"pymacos.backup" => disabled\n\t\t"pymacos.other" => enabled\n\t}\n'
    assert macos.schedule.get("backup").paused is True
    fake_run.calls.clear()
    macos.schedule.remove("backup")  # a paused job is enabled again, so its name can be reused
    assert ["launchctl", "enable", "gui/501/pymacos.backup"] in [call["args"] for call in fake_run.calls]

    fake_run.stdout = ""
    macos.schedule.add("backup", home / "backup.py", every=60)
    fake_run.calls.clear()
    macos.schedule.resume("backup")
    # Not paused, and loaded: left alone, rather than reloaded, which would stop a run in progress.
    assert [call["args"][1] for call in fake_run.calls] == ["print-disabled", "list"]
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
        # The new job's plist, not the old one put back: written beside it under the same name, then moved in.
        if self.name == path.name and b"<integer>60</integer>" in data:
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


def test_schedule_add_reloads_a_read_only_job_it_couldnt_remove(fake_run, home, monkeypatch):
    from pathlib import Path

    macos.schedule.add("backup", home / "backup.py", every=3600)
    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    calls = _failing_bootstrap(monkeypatch, fake_run, fail=False)
    unlink, write_bytes = Path.unlink, Path.write_bytes

    def read_only(method):
        def refuse(self, *args, **kwargs):
            if self == path:
                raise PermissionError(13, "Permission denied", str(self))
            return method(self, *args, **kwargs)

        return refuse

    monkeypatch.setattr(Path, "unlink", read_only(unlink))  # can't be removed...
    monkeypatch.setattr(Path, "write_bytes", read_only(write_bytes))  # ...nor written

    with pytest.raises(PermissionError):
        macos.schedule.add("backup", home / "backup.py", every=60)

    bootstraps = [call for call in calls if call[1] == "bootstrap"]
    assert bootstraps == [["launchctl", "bootstrap", "gui/501", str(path)]]  # the unchanged old job, loaded again
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


def test_schedule_add_says_when_the_replaced_job_could_not_be_put_back(fake_run, home, monkeypatch):
    import subprocess
    import warnings

    from macos import _system

    macos.schedule.add("backup", home / "backup.py", every=3600)

    def launchctl(args, **kwargs):  # every bootstrap fails: the new job's, and the old one's put back
        if args[1] == "bootstrap":
            return subprocess.CompletedProcess(args, 5, "", "Bootstrap failed: 5: Input/output error")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(_system.subprocess, "run", launchctl)
    with warnings.catch_warnings(record=True) as warned:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError) as caught:
            macos.schedule.add("backup", home / "backup.py", every=60)
    told = getattr(caught.value, "__notes__", []) + [str(warning.message) for warning in warned]
    assert any("'backup' it replaced couldn't be put back" in text for text in told)


def test_schedule_jobs_skip_a_plist_edited_into_nonsense(fake_run, home):
    macos.schedule.add("backup", home / "backup.py", every=3600)
    agents = home / "Library" / "LaunchAgents"
    (agents / "pymacos.list.plist").write_bytes(plistlib.dumps(["not", "a", "job"]))
    (agents / "pymacos.days.plist").write_bytes(
        plistlib.dumps({"Label": "pymacos.days", "StartCalendarInterval": [{"Hour": "nine"}], "ProgramArguments": "x"})
    )
    (agents / "pymacos.odd.plist").write_bytes(
        plistlib.dumps({"Label": "pymacos.odd", "StartCalendarInterval": ["09:00"], "WatchPaths": "/tmp"})
    )
    (agents / "pymacos.logs.plist").write_bytes(plistlib.dumps({"Label": "pymacos.logs", "StandardOutPath": ["a", "b"]}))
    infinite = {"Label": "pymacos.forever", "StartCalendarInterval": {"Hour": float("inf")}}
    (agents / "pymacos.forever.plist").write_bytes(plistlib.dumps(infinite))
    # Malformed files: plistlib's XML parser lets out ExpatError and AttributeError, not InvalidFileException.
    (agents / "pymacos.cut.plist").write_bytes(plistlib.dumps({"Label": "pymacos.cut"})[:-20])
    (agents / "pymacos.date.plist").write_text(
        '<?xml version="1.0"?><plist version="1.0"><dict><key>Label</key><date>nope</date></dict></plist>'
    )

    found = {job.name: job for job in macos.schedule.jobs()}
    # The list, the day that isn't a number, the infinite hour, the log list and the malformed files are skipped.
    assert set(found) == {"backup", "odd"}
    assert found["odd"].at == () and found["odd"].when_changed == () and found["odd"].script == Path()


def test_schedule_keeps_only_absolute_folders_of_path(fake_run, home, monkeypatch):
    monkeypatch.setenv("PATH", os.pathsep.join(["/opt/homebrew/bin", ".", "", "bin", "/usr/bin", "/opt/homebrew/bin"]))
    macos.schedule.add("backup", home / "backup.py", every=60)

    assert _plist(home, "backup")["EnvironmentVariables"]["PATH"] == "/opt/homebrew/bin:/usr/bin"


def test_schedule_gives_launchctl_a_time_limit(fake_run, home):
    macos.schedule.add("backup", home / "backup.py", every=60)

    assert all(call.get("timeout") for call in fake_run.calls if call["args"][0] == "launchctl")


def test_schedule_refuses_a_string_for_args_and_weekdays(fake_run, home):
    with pytest.raises(TypeError, match="args must be a list"):
        macos.schedule.add("backup", home / "backup.py", every=60, args="--quiet")  # would be split into letters
    with pytest.raises(TypeError, match="weekdays must be a list"):
        macos.schedule.add("backup", home / "backup.py", at="09:00", weekdays="mon")
    assert not (home / "Library" / "LaunchAgents").exists()


def test_schedule_checks_every_and_the_interpreter(fake_run, home):
    with pytest.raises(ValueError, match="whole seconds"):
        macos.schedule.add("backup", home / "backup.py", every=1.9)  # not silently 1
    with pytest.raises(TypeError, match="every must be a number"):
        macos.schedule.add("backup", home / "backup.py", every="60")
    for never in (float("inf"), float("nan"), 0.5):
        with pytest.raises(ValueError, match="at least 1 second"):
            macos.schedule.add("backup", home / "backup.py", every=never)
    with pytest.raises(FileNotFoundError):
        macos.schedule.add("backup", home / "backup.py", every=60, python=home / "nowhere/python")
    macos.schedule.add("backup", home / "backup.py", every=60.0)
    assert _plist(home, "backup")["StartInterval"] == 60


def test_schedule_goes_by_the_file_name_not_the_label(fake_run, home):
    macos.schedule.add("backup", home / "backup.py", every=60)
    agents = home / "Library" / "LaunchAgents"
    # A copy made by hand keeps the old label: get()/remove() would act on one file and report another.
    (agents / "pymacos.copy.plist").write_bytes((agents / "pymacos.backup.plist").read_bytes())
    assert macos.schedule.get("copy") is None
    assert [job.name for job in macos.schedule.jobs()] == ["backup"]
    # A StartInterval that isn't a number is reported as no interval, not raised.
    edited = plistlib.loads((agents / "pymacos.backup.plist").read_bytes())
    edited["StartInterval"] = "soon"
    (agents / "pymacos.backup.plist").write_bytes(plistlib.dumps(edited))
    assert macos.schedule.get("backup").every is None


def test_schedule_doesnt_take_a_name_spelled_otherwise_for_a_job(fake_run, home):
    macos.schedule.add("Backup", home / "backup.py", every=60)
    agents = home / "Library" / "LaunchAgents"
    # By the disk, not sys.platform, which fake_run sets to darwin: Linux's disks tell case apart.
    if not (agents / "pymacos.backup.plist").exists():
        pytest.skip("this disk tells case apart: the names have files of their own")
    fake_run.calls.clear()

    with pytest.raises(ValueError, match="'Backup'"):
        macos.schedule.add("backup", home / "backup.py", every=60)
    with pytest.raises(ValueError, match="'Backup'"):
        macos.schedule.run_now("backup")
    with pytest.raises(ValueError, match="'Backup'"):
        macos.schedule.pause("backup")
    assert macos.schedule.get("backup") is None
    assert fake_run.calls == []  # launchctl wasn't told about either name
    # remove() would delete Backup's file and leave the job pymacos.Backup loaded, out of jobs()' sight.
    # It only unloads a pymacos.backup an older version may have left loaded without a file.
    assert macos.schedule.remove("backup") is False
    told = [call["args"] for call in fake_run.calls if call["args"][1] != "print-disabled"]
    assert told == [["launchctl", "bootout", "gui/501/pymacos.backup"]]
    assert [job.name for job in macos.schedule.jobs()] == ["Backup"]
    assert macos.schedule.remove("Backup") is True


def test_schedule_remove_unloads_a_job_an_older_version_left_without_a_file(fake_run, home, monkeypatch):
    agents = home / "Library" / "LaunchAgents"
    # What adding "backup", then "Backup" did before: Backup's file (pymacos.Backup.plist, its label
    # pymacos.Backup) where backup's was, and pymacos.backup still loaded, here paused too.
    macos.schedule.add("Backup", home / "backup.py", every=60)
    if not (agents / "pymacos.backup.plist").exists():
        pytest.skip("this disk tells case apart: the names have files of their own")
    monkeypatch.setattr(macos.schedule, "_paused", lambda **kwargs: ["backup"])
    fake_run.calls.clear()

    assert macos.schedule.remove("backup") is False
    # Unloaded and its pause lifted, as remove() does for any job; Backup's file is left alone.
    assert [call["args"] for call in fake_run.calls] == [
        ["launchctl", "bootout", "gui/501/pymacos.backup"],
        ["launchctl", "enable", "gui/501/pymacos.backup"],
    ]
    assert [path.name for path in agents.iterdir()] == ["pymacos.Backup.plist"]


def test_schedule_doesnt_take_a_prefix_or_extension_spelled_otherwise_for_another_name(fake_run, home):
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "pymacos.backup.PLIST").write_bytes(b"renamed by hand")
    if not (agents / "pymacos.backup.plist").exists():
        pytest.skip("this disk tells case apart: the names have files of their own")
    # Not "a job named 'backup' exists: use 'backup'": the file is replaced, as before.
    macos.schedule.add("backup", home / "backup.py", every=60)
    assert macos.schedule.get("backup").every == 60


def test_schedule_add_reads_the_paused_jobs_once(fake_run, home):
    macos.schedule.add("backup", home / "backup.py", every=60)
    listings = [call["args"] for call in fake_run.calls if call["args"][:2] == ["launchctl", "print-disabled"]]
    assert len(listings) == 1


def test_schedule_warns_when_other_users_could_change_the_script(fake_run, home):
    import warnings

    shared = home / "shared"
    shared.mkdir()
    shared.chmod(0o777)  # writable by anyone, no sticky bit: the script could be swapped
    script = shared / "job.py"
    script.write_text("print('hi')")
    script.chmod(0o644)  # whatever the umask: only the folder is open to others
    with pytest.warns(RuntimeWarning, match="other users may replace what's in"):
        macos.schedule.add("swapped", script, every=60)

    shared.chmod(0o1777)  # the sticky bit, as on /tmp: only its owner may rename it
    script.chmod(0o666)
    with pytest.warns(RuntimeWarning, match="other users may change"):
        macos.schedule.add("swapped", script, every=60)

    script.chmod(0o644)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        macos.schedule.add("swapped", script, every=60)  # only its owner may change it: no warning
        macos.schedule.add("backup", home / "backup.py", every=60)


def test_schedule_trusts_folders_only_the_admin_group_may_write_in(monkeypatch, tmp_path):
    from macos import schedule

    script = tmp_path / "job.py"
    script.write_text("print('hi')")
    script.chmod(0o644)  # whatever the umask
    real_stat = os.stat

    def stat_as(gid):
        def fake(path, *args, **kwargs):
            found = real_stat(path, *args, **kwargs)
            if path == os.path.realpath(str(tmp_path)):  # Homebrew's folders: drwxrwxr-x you:admin
                return os.stat_result((0o40775, *found[1:5], gid, *found[6:]))
            return found
        return fake

    monkeypatch.setattr(schedule.os, "stat", stat_as(schedule._ADMIN_GROUP))
    assert schedule._swappable(script) is None  # its members can use sudo anyway
    monkeypatch.setattr(schedule.os, "stat", stat_as(schedule._ADMIN_GROUP + 1))
    assert schedule._swappable(script) == "other users may replace what's in {}".format(os.path.realpath(str(tmp_path)))


def _notes_of(error, reported):
    """What add_note() told: the error's notes (Python 3.11+), or the RuntimeWarnings it fell back to."""
    return " ".join(getattr(error, "__notes__", [])) + " ".join(
        str(item.message) for item in reported if issubclass(item.category, RuntimeWarning)
    )


def _refusing_launchctl(monkeypatch, fake_run, refused, *, disabled=(), also=()):
    """
    Record launchctl's commands; ``refused`` fails (every time), and so does any in ``also``.

    ``disabled`` names the jobs ``launchctl print-disabled`` reports as paused.
    """
    import subprocess

    from macos import _system

    calls = []
    listing = "".join('\t\t"pymacos.{}" => disabled\n'.format(name) for name in disabled)

    def launchctl(args, **kwargs):
        calls.append(list(args))
        if args[1] == refused or args[1] in also:
            return subprocess.CompletedProcess(args, 5, "", "{} failed: 5: Input/output error".format(args[1]))
        return subprocess.CompletedProcess(args, 0, listing if args[1] == "print-disabled" else "", "")

    monkeypatch.setattr(_system.subprocess, "run", launchctl)
    return calls


def test_schedule_pause_leaves_a_job_it_couldnt_unload_as_it_was(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    calls = _refusing_launchctl(monkeypatch, fake_run, "bootout")

    with pytest.raises(macos.errors.CommandError, match="bootout failed"):
        macos.schedule.pause("backup")

    # Disabled before unloading (a refusal there changes nothing), and enabled again when unloading
    # failed: not left loaded now, and gone at the next login.
    assert [call[1] for call in calls] == ["print-disabled", "disable", "bootout", "enable"]
    assert calls[-1] == ["launchctl", "enable", "gui/501/pymacos.backup"]


def test_schedule_pause_says_when_the_job_couldnt_be_enabled_again(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    _refusing_launchctl(monkeypatch, fake_run, "bootout", also=("enable",))

    with warnings.catch_warnings(record=True) as reported:  # before Python 3.11, a note is a RuntimeWarning
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="bootout failed") as caught:
            macos.schedule.pause("backup")
    assert "won't be at the next login" in _notes_of(caught.value, reported)


def test_schedule_resume_pauses_again_a_paused_job_it_couldnt_load(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    calls = _refusing_launchctl(monkeypatch, fake_run, "bootstrap", disabled=["backup"])

    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="bootstrap failed") as caught:
            macos.schedule.resume("backup")

    # Enabled and unloaded, it would have come back at the next login as if resumed: paused again instead.
    assert [call[1] for call in calls] == ["print-disabled", "bootout", "enable", "bootstrap", "disable"]
    assert calls[-1] == ["launchctl", "disable", "gui/501/pymacos.backup"]
    assert _notes_of(caught.value, reported) == ""


def test_schedule_resume_says_when_a_paused_job_couldnt_be_paused_again(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    calls = _refusing_launchctl(monkeypatch, fake_run, "bootstrap", disabled=["backup"], also=("disable",))

    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="bootstrap failed") as caught:
            macos.schedule.resume("backup")

    assert [call[1] for call in calls] == ["print-disabled", "bootout", "enable", "bootstrap", "disable"]
    assert "couldn't be paused again either" in _notes_of(caught.value, reported)


def test_schedule_resume_says_when_a_loaded_job_stays_unloaded(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    # Not paused, nor loaded: resume() loads it.
    calls = _refusing_launchctl(monkeypatch, fake_run, "bootstrap", also=("list",))

    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="bootstrap failed") as caught:
            macos.schedule.resume("backup")

    # Not paused by mistake.
    assert [call[1] for call in calls] == ["print-disabled", "list", "bootout", "enable", "bootstrap"]
    assert "stays unloaded until the next login" in _notes_of(caught.value, reported)


def test_schedule_pause_leaves_a_paused_job_paused_when_it_cant_be_unloaded(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    calls = _refusing_launchctl(monkeypatch, fake_run, "bootout", disabled=["backup"])

    with pytest.raises(macos.errors.CommandError, match="bootout failed"):
        macos.schedule.pause("backup")

    # Paused before the call: not enabled again by the rollback, which would bring it back at the next login.
    assert [call[1] for call in calls] == ["print-disabled", "disable", "bootout"]


def test_schedule_pause_unloads_first_when_launchctl_wont_say_whether_its_paused(fake_run, home, monkeypatch):
    from macos import schedule

    macos.schedule.add("backup", home / "backup.py", every=60)

    def silent(strict=False):
        raise macos.errors.CommandTimeoutError(["launchctl", "print-disabled"], 60)

    monkeypatch.setattr(schedule, "_paused", silent)  # launchctl print-disabled out of time (an error reads as {})
    calls = _refusing_launchctl(monkeypatch, fake_run, "none")
    macos.schedule.pause("backup")
    assert [call[1] for call in calls] == ["bootout", "disable"]

    # Unloading refused: nothing done, so nothing to put back (enabling could resume a job that was paused).
    calls = _refusing_launchctl(monkeypatch, fake_run, "bootout")
    with pytest.raises(macos.errors.CommandError, match="bootout failed"):
        macos.schedule.pause("backup")
    assert [call[1] for call in calls] == ["bootout"]


def test_schedule_pause_doesnt_take_an_unanswered_question_for_not_paused(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)

    calls = _refusing_launchctl(monkeypatch, fake_run, "print-disabled")  # an error: before, read as "none paused"
    macos.schedule.pause("backup")
    assert [call[1] for call in calls] == ["print-disabled", "bootout", "disable"]  # the unknown state's order

    calls = _refusing_launchctl(monkeypatch, fake_run, "print-disabled", also=("disable",))
    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="disable failed") as caught:
            macos.schedule.pause("backup")
    assert "couldn't be paused: unless it was paused already, it comes back" in _notes_of(caught.value, reported)

    # The other functions still read "won't say" as none paused, as before: listing jobs doesn't fail for it.
    calls = _refusing_launchctl(monkeypatch, fake_run, "print-disabled")
    assert [job.name for job in macos.schedule.jobs()] == ["backup"]


def test_schedule_resume_says_so_when_launchctl_wont_tell_whether_the_job_was_paused(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    calls = _refusing_launchctl(monkeypatch, fake_run, "print-disabled", also=("bootstrap",))

    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="bootstrap failed") as caught:
            macos.schedule.resume("backup")

    # Not paused again (it may never have been), but not said to be "not paused" either.
    assert [call[1] for call in calls] == ["print-disabled", "bootout", "enable", "bootstrap"]
    notes = _notes_of(caught.value, reported)
    assert "no longer paused (launchctl wouldn't say whether it was)" in notes and "stays unloaded" not in notes


def test_schedule_resume_says_when_it_couldnt_enable_a_job_it_unloaded(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    # Not paused, nor loaded: unloaded to be reloaded.
    calls = _refusing_launchctl(monkeypatch, fake_run, "enable", also=("list",))

    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="enable failed") as caught:
            macos.schedule.resume("backup")

    assert [call[1] for call in calls] == ["print-disabled", "list", "bootout", "enable"]
    assert "stays unloaded until the next login" in _notes_of(caught.value, reported)

    # A paused job whose enabling failed is still paused: disabled again, which changes nothing, and no note.
    calls = _refusing_launchctl(monkeypatch, fake_run, "enable", disabled=["backup"])
    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="enable failed") as caught:
            macos.schedule.resume("backup")
    assert [call[1] for call in calls] == ["print-disabled", "bootout", "enable", "disable"]
    assert _notes_of(caught.value, reported) == ""


def test_schedule_resume_tells_whether_enabling_took_effect(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)

    # Paused, enabling refused and disabling again refused too: still disabled, so it only "may" run.
    _refusing_launchctl(monkeypatch, fake_run, "enable", disabled=["backup"], also=("disable",))
    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="enable failed") as caught:
            macos.schedule.resume("backup")
    assert "it may run at the next login" in _notes_of(caught.value, reported)

    # launchctl wouldn't say whether it was paused, and enabling was refused: it may still be.
    _refusing_launchctl(monkeypatch, fake_run, "print-disabled", also=("enable",))
    with warnings.catch_warnings(record=True) as reported:
        warnings.simplefilter("always")
        with pytest.raises(macos.errors.CommandError, match="enable failed") as caught:
            macos.schedule.resume("backup")
    assert "unless it is, it comes back at the next login" in _notes_of(caught.value, reported)


def test_schedule_resume_reloads_a_job_that_isnt_loaded(fake_run, home, monkeypatch):
    macos.schedule.add("backup", home / "backup.py", every=60)
    calls = _refusing_launchctl(monkeypatch, fake_run, "list")  # not paused, but not loaded either

    macos.schedule.resume("backup")

    assert [call[1] for call in calls] == ["print-disabled", "list", "bootout", "enable", "bootstrap"]


def test_schedule_writes_a_plist_only_you_may_write(fake_run, home):
    import stat

    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    old = os.umask(0o002)  # a new file would be 0o664, which launchd refuses
    try:
        macos.schedule.add("backup", home / "backup.py", every=60)
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
        path.chmod(0o666)  # nor does replacing a job keep the old file's mode
        macos.schedule.add("backup", home / "backup.py", every=120)
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    finally:
        os.umask(old)


def test_schedule_writes_the_replaced_plist_back_only_you_may_write(fake_run, home, monkeypatch):
    import stat

    macos.schedule.add("backup", home / "backup.py", every=3600)
    path = home / "Library/LaunchAgents/pymacos.backup.plist"
    path.chmod(0o664)
    _failing_bootstrap(monkeypatch, fake_run)

    with pytest.raises(macos.errors.CommandError):
        macos.schedule.add("backup", home / "backup.py", every=60)

    assert _plist(home, "backup")["StartInterval"] == 3600
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_schedule_says_what_is_wrong_with_at_and_weekdays_of_another_type(fake_run, home):
    script = home / "backup.py"
    with pytest.raises(TypeError, match="at must be a time"):
        macos.schedule.add("x", script, at=["09:00", 9])
    with pytest.raises(TypeError, match="at must be a time"):
        macos.schedule.add("x", script, at=9)
    with pytest.raises(TypeError, match="weekdays must be names"):
        macos.schedule.add("x", script, at="09:00", weekdays=[1])
    with pytest.raises(TypeError, match="weekdays must be names"):
        macos.schedule.add("x", script, at="09:00", weekdays=[b"mon"])
    assert not (home / "Library" / "LaunchAgents").exists()


def test_schedule_checks_the_interpreter_is_executable_and_looks_a_command_up_on_path(fake_run, home, monkeypatch):
    script = home / "backup.py"
    (home / "venv/bin").mkdir(parents=True)
    activate = home / "venv/bin/activate"
    activate.write_text("")
    with pytest.raises(ValueError, match="executable interpreter"):
        macos.schedule.add("x", script, every=60, python=activate)  # launchd couldn't start it

    python = home / "venv/bin/python3.99"
    python.write_text("")
    python.chmod(0o755)
    monkeypatch.setenv("PATH", str(home / "venv/bin"))
    monkeypatch.chdir(home)
    macos.schedule.add("x", script, every=60, python="python3.99")
    assert _plist(home, "x")["ProgramArguments"][0] == str(python)
    with pytest.raises(FileNotFoundError, match="isn't a command on PATH"):
        macos.schedule.add("x", script, every=60, python="python0")  # not <cwd>/python0


def test_schedule_says_what_is_wrong_with_args_a_long_name_and_a_huge_every(fake_run, home):
    script = home / "backup.py"
    with pytest.raises(ValueError, match="args can't hold control characters"):
        macos.schedule.add("x", script, every=60, args=["a\x01b"])
    with pytest.raises(ValueError, match="at most 200 characters"):
        macos.schedule.add("a" * 300, script, every=60)
    for huge in (1e30, 2 ** 40, 2 ** 31):
        with pytest.raises(ValueError, match="at most 2147483647 seconds"):
            macos.schedule.add("x", script, every=huge)
    assert not (home / "Library" / "LaunchAgents").exists()
    macos.schedule.add("x", script, every=2 ** 31 - 1, args=["tab\there", "two\nlines"])
    assert _plist(home, "x")["ProgramArguments"][2:] == ["tab\there", "two\nlines"]


def test_schedule_run_now_says_when_the_job_is_paused_or_not_loaded(fake_run, home, monkeypatch):
    import subprocess

    from macos import _system

    macos.schedule.add("backup", home / "backup.py", every=60)
    listing = ""

    def launchctl(args, **kwargs):
        if args[1] == "kickstart":
            return subprocess.CompletedProcess(args, 113, "", 'Could not find service "pymacos.backup" in domain')
        return subprocess.CompletedProcess(args, 0, listing if args[1] == "print-disabled" else "", "")

    monkeypatch.setattr(_system.subprocess, "run", launchctl)
    listing = '\t\t"pymacos.backup" => disabled\n'
    with pytest.raises(macos.errors.CommandError, match="is paused: resume") as caught:
        macos.schedule.run_now("backup")
    assert caught.value.returncode == 113 and "Could not find service" in str(caught.value)
    listing = ""
    with pytest.raises(macos.errors.CommandError, match="isn't loaded: resume"):
        macos.schedule.run_now("backup")
