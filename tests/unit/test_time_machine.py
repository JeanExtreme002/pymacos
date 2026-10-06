"""Unit tests for :mod:`macos.time_machine`. They run on any platform."""

from datetime import datetime

import pytest

import macos


def test_time_machine_status(fake_run):
    fake_run.stdout = 'Backup session status:\n{\n    ClientID = "com.apple.backupd";\n    Percent = "0.42";\n'
    fake_run.stdout += "    Running = 1;\n}\n"
    assert macos.time_machine.is_backing_up() is True
    assert macos.time_machine.progress() == 0.42

    fake_run.stdout = 'Backup session status:\n{\n    Percent = "-1";\n    Running = 0;\n}\n'
    assert macos.time_machine.is_backing_up() is False and macos.time_machine.progress() is None


def test_time_machine_destinations_and_last_backup(fake_run):
    fake_run.stdout = "====================================================\nName          : Backup Disk\nKind          : Local\n"
    assert macos.time_machine.destinations() == ["Backup Disk"]
    fake_run.stdout = "/Volumes/.timemachine/ABC/2026-09-28-231004.backup/2026-09-28-231004.backup\n"
    assert macos.time_machine.last_backup() == datetime(2026, 9, 28, 23, 10, 4)
    fake_run.stdout = "Failed to mount backup destination, error: ...\n"  # printed with a success status
    assert macos.time_machine.last_backup() is None

    fake_run.stdout = "tmutil: No destinations configured.\n"
    assert macos.time_machine.destinations() == []
    with pytest.raises(macos.MacOSError, match="no backup disk"):
        macos.time_machine.backup_now()


def test_time_machine_exclusions(fake_run, tmp_path):
    folder = tmp_path / "node_modules"
    folder.mkdir()
    macos.time_machine.exclude(folder)
    assert fake_run.args == ["tmutil", "addexclusion", str(folder)]
    macos.time_machine.include(folder)
    assert fake_run.args == ["tmutil", "removeexclusion", str(folder)]

    fake_run.stdout = "[Excluded]  {}\n".format(folder)
    assert macos.time_machine.is_excluded(folder) is True
    fake_run.stdout = "[Included]  {}\n".format(folder)
    assert macos.time_machine.is_excluded(folder) is False

    with pytest.raises(FileNotFoundError):
        macos.time_machine.exclude(tmp_path / "missing")


@pytest.mark.parametrize(
    "returncode, stdout, stderr",
    [
        (80, "", "tmutil: latestbackup requires Full Disk Access privileges.\n"),
        (0, "tmutil: latestbackup requires Full Disk Access privileges.\n", ""),
        (1, "", "ls: /Volumes/Backups: Operation not permitted\n"),
    ],
)
def test_time_machine_last_backup_without_full_disk_access(fake_run, returncode, stdout, stderr):
    fake_run.returncode, fake_run.stdout, fake_run.stderr = returncode, stdout, stderr

    with pytest.raises(macos.PermissionDeniedError, match="Full Disk Access"):
        macos.time_machine.last_backup()


def test_time_machine_last_backup_on_a_disk_named_like_an_error(fake_run):
    fake_run.stdout = "/Volumes/Full Disk Access/Backups.backupdb/My Mac/2026-09-28-231004\n"
    assert macos.time_machine.last_backup() == datetime(2026, 9, 28, 23, 10, 4)


def test_time_machine_last_backup_none_when_there_is_none(fake_run):
    fake_run.returncode, fake_run.stderr = 1, "No machine directory found for host.\n"
    assert macos.time_machine.last_backup() is None
