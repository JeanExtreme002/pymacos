"""Tests of :mod:`macos.schedule` against the real system. Skipped outside macOS."""

import os
import time

import pytest

import macos

from tests.helpers import ON_GITHUB, switch


@pytest.mark.skipif(
    not (ON_GITHUB or switch("PYMACOS_SCHEDULE_TESTS")),
    reason="adds a launch agent, which macOS announces: set PYMACOS_SCHEDULE_TESTS=1 to run",
)
def test_schedule_runs_the_script(tmp_path):
    script = tmp_path / "job.py"
    output = tmp_path / "out.txt"
    script.write_text("import sys\nopen(sys.argv[1], 'w').write(' '.join(sys.argv[2:]))\nprint('done')\n")
    name = "pymacos-test-{}".format(os.getpid())
    try:
        job = macos.schedule.add(name, script, every=3600, args=[str(output), "two words"])
        assert job.every == 3600 and job.script == script and name in [found.name for found in macos.schedule.jobs()]
        macos.schedule.run_now(name)
        deadline = time.monotonic() + 30
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert output.read_text() == "two words"
        deadline = time.monotonic() + 10
        while macos.schedule.get(name).last_exit_status is None and time.monotonic() < deadline:
            time.sleep(0.2)
        job = macos.schedule.get(name)
        assert job.last_exit_status == 0 and "done" in job.log.read_text()
        assert job.args == (str(output), "two words")
        macos.schedule.pause(name)
        assert macos.schedule.get(name).paused
        macos.schedule.resume(name)
        assert not macos.schedule.get(name).paused
    finally:
        assert macos.schedule.remove(name)
        (macos.schedule._log(name)).unlink(missing_ok=True)
    assert macos.schedule.get(name) is None


def _wait_for(path, text="", seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and text in path.read_text():
            return True
        time.sleep(0.2)
    return False


@pytest.mark.skipif(
    not (ON_GITHUB or switch("PYMACOS_SCHEDULE_TESTS")),
    reason="adds a launch agent, which macOS announces: set PYMACOS_SCHEDULE_TESTS=1 to run",
)
def test_schedule_runs_when_a_folder_changes(tmp_path):
    watched = tmp_path / "inbox"
    watched.mkdir()
    script = tmp_path / "job.py"
    output = tmp_path / "out.txt"
    script.write_text(
        "import os, sys\nopen(sys.argv[1] + '.tmp', 'w').write(','.join(sorted(os.listdir(sys.argv[2]))))\n"
        "os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
    )
    name = "pymacos-test-watch-{}".format(os.getpid())
    try:
        job = macos.schedule.add(name, script, when_changed=watched, args=[str(output), str(watched)])
        assert job.when_changed == (watched,)
        time.sleep(1)  # let launchd start watching
        (watched / "new.txt").write_text("hi")
        # launchd may also run it once as it loads, before the file exists: wait for the run that sees it.
        assert _wait_for(output, "new.txt"), "the job didn't run when the folder changed"
    finally:
        macos.schedule.remove(name)
        macos.schedule._log(name).unlink(missing_ok=True)


@pytest.mark.skipif(
    not (ON_GITHUB or switch("PYMACOS_SCHEDULE_TESTS")),
    reason="adds a launch agent, which macOS announces: set PYMACOS_SCHEDULE_TESTS=1 to run",
)
def test_schedule_runs_when_a_disk_is_mounted(tmp_path):
    import subprocess

    script = tmp_path / "job.py"
    output = tmp_path / "out.txt"
    script.write_text("import sys\nopen(sys.argv[1], 'a').write('mounted\\n')\n")
    image = tmp_path / "disk.dmg"
    subprocess.run(
        ["hdiutil", "create", "-quiet", "-size", "2m", "-fs", "HFS+", "-volname", "pymacos-test", str(image)], check=True
    )
    name = "pymacos-test-mount-{}".format(os.getpid())
    mount = tmp_path / "mnt"
    try:
        job = macos.schedule.add(name, script, at_mount=True, args=[str(output)])
        assert job.at_mount is True
        time.sleep(1)
        attached = subprocess.run(
            ["hdiutil", "attach", "-quiet", "-nobrowse", "-mountpoint", str(mount), str(image)], capture_output=True
        )
        if attached.returncode != 0:
            pytest.skip("can't mount a disk image here: {}".format(attached.stderr.decode().strip()))
        assert _wait_for(output, "mounted"), "the job didn't run when the disk was mounted"
    finally:
        subprocess.run(["hdiutil", "detach", "-quiet", "-force", str(mount)], capture_output=True)
        macos.schedule.remove(name)
        macos.schedule._log(name).unlink(missing_ok=True)
