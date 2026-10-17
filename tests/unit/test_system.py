"""Unit tests for :mod:`macos.system`. They run on any platform."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import macos


def test_system_commands(fake_run):
    fake_run.stdout = "24G90\n"
    assert macos.system.build() == "24G90"
    assert fake_run.args == ["sw_vers", "-buildVersion"]

    fake_run.stdout = "My Mac\n"
    assert macos.system.computer_name() == "My Mac"
    assert fake_run.args == ["scutil", "--get", "ComputerName"]
    assert all(call["timeout"] for call in fake_run.calls)  # a wedged command mustn't hang the script


def test_eject(fake_run, monkeypatch):
    backup = macos.system.Volume("Backup", Path("/Volumes/Backup"), 10, 5, False, True, True)
    root = macos.system.Volume("Macintosh HD", Path("/"), 10, 5, True, False, False)
    monkeypatch.setattr(macos.system, "volumes", lambda: [root, backup])

    macos.system.eject("Backup")
    assert fake_run.args == ["diskutil", "eject", "/Volumes/Backup"]
    macos.system.eject("/Volumes/Backup/")
    assert fake_run.args[-1] == "/Volumes/Backup"
    macos.system.eject(backup)
    assert fake_run.args[-1] == "/Volumes/Backup"

    with pytest.raises(ValueError, match="startup disk"):
        macos.system.eject("Macintosh HD")
    with pytest.raises(ValueError, match="no mounted volume"):
        macos.system.eject("Nope")


DISSENT = (
    "Unmount of disk13 failed: at least one volume could not be unmounted\n"
    "Unmount was dissented by PID 4123 (/Applications/Preview.app/Contents/MacOS/Preview)"
)


class Answers(list):
    """The (returncode, stderr) each next command gets, and when each one started on the fake clock."""

    took = 0.0  # how long each command runs
    starts: list


@pytest.fixture
def answers(fake_run, monkeypatch):
    """Answer each command with the next answer queued, on a clock that only sleep() and commands move."""
    queued = Answers()
    queued.starts = []
    clock = [0.0]

    def run(args, **kwargs):
        fake_run.calls.append({"args": list(args), **kwargs})
        queued.starts.append(clock[0])
        clock[0] += queued.took
        returncode, stderr = queued.pop(0) if queued else (0, "")
        return subprocess.CompletedProcess(args, returncode, "", stderr)

    monkeypatch.setattr(macos._system.subprocess, "run", run)
    monkeypatch.setattr(macos.system.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(macos.system.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return queued


@pytest.fixture
def backup(monkeypatch):
    volume = macos.system.Volume("Backup", Path("/Volumes/Backup"), 10, 5, False, True, True)
    monkeypatch.setattr(macos.system, "volumes", lambda: [volume])
    return volume


def test_eject_waits_out_a_volume_busy_for_a_moment(answers, fake_run, backup):
    # Right after mounting, a system service can hold the volume briefly.
    answers.extend([(1, "Volume failed to eject"), (1, "Volume failed to eject")])
    macos.system.eject("Backup")
    assert [call["args"] for call in fake_run.calls] == [["diskutil", "eject", "/Volumes/Backup"]] * 3


def test_eject_names_the_process_still_using_the_volume(answers, fake_run, backup):
    answers.extend([(1, DISSENT)] * 100)
    with pytest.raises(macos.errors.CommandError, match=r"dissented by PID 4123 \(.*Preview\)"):
        macos.system.eject("Backup")
    assert 2 < len(fake_run.calls) < 100  # retried for a few seconds, then gave up


def test_eject_starts_no_try_after_the_wait(answers, backup):
    # Slow commands must not carry a try past the deadline: the sleep is capped by what's left.
    answers.took = 0.1  # a try ends at 4.9 s: an uncapped 0.5 s sleep would start the next at 5.4 s
    answers.extend([(1, DISSENT)] * 100)
    with pytest.raises(macos.errors.CommandError):
        macos.system.eject("Backup")
    assert max(answers.starts) <= macos.system._BUSY_WAIT


def test_eject_does_not_retry_other_errors(answers, fake_run, backup):
    answers.append((1, "Unable to find disk for /Volumes/Backup"))
    with pytest.raises(macos.errors.CommandError, match="Unable to find disk"):
        macos.system.eject("Backup")
    assert len(fake_run.calls) == 1


def test_unmount_image_waits_out_a_busy_image(answers, fake_run):
    answers.append((16, 'hdiutil: couldn\'t unmount "disk13" - Resource busy'))
    macos.system.unmount_image("/Volumes/Tool")
    assert [call["args"] for call in fake_run.calls] == [["hdiutil", "detach", "/Volumes/Tool"]] * 2


def test_eject_refuses_folders_and_hidden_system_volumes(fake_run, monkeypatch, tmp_path):
    monkeypatch.setattr(macos.system, "volumes", lambda: [])

    for target in (tmp_path, "/System/Volumes/Data"):
        with pytest.raises(ValueError, match="no mounted volume"):
            macos.system.eject(target)
    assert fake_run.calls == []


def test_eject_refuses_ambiguous_names_and_fixed_volumes(fake_run, monkeypatch):
    first = macos.system.Volume("Untitled", Path("/Volumes/Untitled"), 10, 5, False, True, True)
    second = macos.system.Volume("Untitled", Path("/Volumes/Untitled 1"), 10, 5, False, True, True)
    fixed = macos.system.Volume("Data", Path("/Volumes/Data"), 10, 5, True, False, False)
    monkeypatch.setattr(macos.system, "volumes", lambda: [first, second, fixed])

    with pytest.raises(ValueError, match="more than one volume"):
        macos.system.eject("Untitled")
    macos.system.eject("/Volumes/Untitled 1")
    assert fake_run.args == ["diskutil", "eject", "/Volumes/Untitled 1"]

    with pytest.raises(ValueError, match="can't be ejected"):
        macos.system.eject("Data")


def test_microphone_in_use(monkeypatch):
    from macos import audio

    properties = {(1, "prs#"): [101, 102], (101, "piri"): 0, (102, "piri"): 0}

    def fake_property(target, selector, scope=None, element=0):
        value = properties.get((target, selector))
        if value is None:
            return None
        values = value if isinstance(value, list) else [value]
        return b"".join(number.to_bytes(4, "little") for number in values)

    monkeypatch.setattr(audio, "_property", fake_property)
    monkeypatch.setattr(audio, "_uint", lambda target, selector: properties.get((target, selector)))
    assert macos.system.microphone_in_use() is False
    properties[(102, "piri")] = 1  # one app records
    assert macos.system.microphone_in_use() is True

    # Before macOS 14 there's no process list: an input device running counts.
    del properties[(1, "prs#")]
    monkeypatch.setattr(audio, "inputs", lambda: [audio.Device(9, "Mic", "mic", "builtin", False, True)])
    assert macos.system.microphone_in_use() is False
    properties[(9, "gone")] = 1
    assert macos.system.microphone_in_use() is True


def test_camera_in_use(monkeypatch):
    running = {1: [34, 35], 34: [0], 35: [0]}
    monkeypatch.setattr(
        macos.system,
        "_camera_property",
        lambda target, selector: b"".join(number.to_bytes(4, "little") for number in running[target]),
    )

    assert macos.system.camera_in_use() is False
    running[35] = [1]
    assert macos.system.camera_in_use() is True


def test_wait_for_idle_and_activity(monkeypatch):
    from datetime import timedelta

    system = macos.system
    clock = {"now": 0.0}
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(system.time, "sleep", sleep)
    monkeypatch.setattr(system.time, "monotonic", lambda: clock["now"])
    idle = iter([10.0, 250.0, 300.0])
    monkeypatch.setattr(system, "idle_time", lambda: timedelta(seconds=next(idle)))

    assert system.wait_for_idle(timedelta(minutes=5)) is True
    assert sleeps[:2] == [290.0, 50.0]  # it sleeps until the goal could be reached, not in small steps

    # Idle for 0.01 s when it starts; input 0.1 s later, so 0.1 s idle after one 0.2 s interval:
    # still more than the first reading, but less than the 0.21 s it would be without input.
    readings = iter([0.01, 0.1])
    monkeypatch.setattr(system, "idle_time", lambda: timedelta(seconds=next(readings)))
    assert system.wait_for_activity() is True

    monkeypatch.setattr(system, "idle_time", lambda: timedelta(seconds=clock["now"]))  # nobody around
    assert system.wait_for_activity(timeout=1) is False
    monkeypatch.setattr(system, "idle_time", lambda: timedelta(seconds=1))
    assert system.wait_for_idle(60, timeout=0) is False
    with pytest.raises(ValueError):
        system.wait_for_idle(-1)


_UPDATES = """Software Update Tool

Finding available software
Software Update found the following new or updated software:
* Label: Safari27.0SequoiaAuto-27.0
\tTitle: Safari, Version: 27.0, Size: 238423KiB, Recommended: YES,\x20
* Label: macOS Sequoia\xa015.8.1-24H32
\tTitle: macOS Sequoia\xa015.8.1, Version: 15.8.1, Size: 2310804KiB, Recommended: YES, Action: restart,\x20
"""


def test_available_updates(fake_run):
    fake_run.stdout = _UPDATES
    safari, sequoia = macos.system.available_updates()

    assert (safari.label, safari.title, safari.version, safari.size, safari.restart) == (
        "Safari27.0SequoiaAuto-27.0", "Safari", "27.0", 238423 * 1024, False,
    )  # fmt: skip
    assert sequoia.label == "macOS Sequoia\xa015.8.1-24H32"  # exact, as softwareupdate --install takes it
    assert sequoia.title == "macOS Sequoia 15.8.1" and sequoia.recommended and sequoia.restart
    fake_run.stdout = "Software Update Tool\n\nFinding available software\n"
    assert macos.system.available_updates() == []


def test_mount_image(fake_run, tmp_path):
    image = tmp_path / "Tool.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = (
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>system-entities</key><array>'
        "<dict><key>content-hint</key><string>GUID_partition_scheme</string></dict>"
        "<dict><key>mount-point</key><string>/Volumes/Tool</string></dict></array></dict></plist>"
    )

    assert macos.system.mount_image(image) == Path("/Volumes/Tool")
    assert fake_run.args[:2] == ["hdiutil", "attach"] and fake_run.calls[-1]["input"] == "Y\n"  # accepts a license
    macos.system.unmount_image("/Volumes/Tool", force=True)
    assert fake_run.args == ["hdiutil", "detach", "/Volumes/Tool", "-force"]
    macos.system.unmount_image("-force")  # a mount point named like an option is still a path
    assert fake_run.args == ["hdiutil", "detach", str(Path("-force").absolute())]
    macos.system.unmount_image("disk4")  # hdiutil also takes a disk's name: left as it is
    assert fake_run.args == ["hdiutil", "detach", "disk4"]
    with pytest.raises(FileNotFoundError):
        macos.system.mount_image(tmp_path / "missing.dmg")


def test_mount_image_skips_a_license_shown_before_the_plist(fake_run, tmp_path):
    image = tmp_path / "Tool.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = (
        "Software License Agreement\nPress Y to agree.\n"
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>system-entities</key><array>'
        "<dict><key>mount-point</key><string>/Volumes/Tool</string></dict></array></dict></plist>"
    )

    assert macos.system.mount_image(image) == Path("/Volumes/Tool")


def test_cpu_and_memory_argument_checks():
    with pytest.raises(ValueError, match="interval"):
        macos.system.cpu_usage(0)
    usage = macos.system.MemoryUsage(total=100, used=25, wired=5, compressed=5, cached=10)
    assert (usage.free, usage.percent) == (75, 0.25)


def test_mount_image_detaches_an_image_without_a_volume(fake_run, tmp_path):
    image = tmp_path / "Disk.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = (
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>system-entities</key><array>'
        "<dict><key>dev-entry</key><string>/dev/disk9s1</string></dict>"
        "<dict><key>dev-entry</key><string>/dev/disk9</string></dict></array></dict></plist>"
    )

    with pytest.raises(macos.MacOSError, match="no volume to mount"):
        macos.system.mount_image(image)
    assert fake_run.args == ["hdiutil", "detach", "/dev/disk9", "-force"]  # the whole disk, not left attached


def test_cpu_usage_survives_a_counter_wrapping_around(monkeypatch):
    system = macos.system
    samples = iter([(2**32 - 100, 50, 1000, 0), (100, 150, 1200, 0)])  # user wrapped: +200
    monkeypatch.setattr(system, "_cpu_ticks", lambda: next(samples))
    monkeypatch.setattr(system.time, "sleep", lambda seconds: None)

    assert system.cpu_usage() == 0.6  # (200 user + 100 system) busy of 500 ticks


def test_process_checks():
    with pytest.raises(ValueError, match="pid must be positive"):
        macos.system.process(0)


def test_process_names_cut_by_the_kernel():
    from pathlib import Path

    long_path = Path("/Applications/Google Chrome.app/Contents/Frameworks/Google Chrome Helper (Renderer)")
    name = macos.system._process_name
    assert name(b"Code Helper (Plugin)", b"Code Helper (Pl", Path("/x/Code Helper (Plugin)")) == "Code Helper (Plugin)"
    assert name(b"Google Chrome Helper (Rendere", b"Google Chrome H", long_path) == "Google Chrome Helper (Rendere"
    beta = long_path.with_name("Google Chrome Helper (Renderer) Beta")  # 36 characters: cut to 31
    assert name(b"Google Chrome Helper (Renderer)", b"Google Chrome H", beta) == "Google Chrome Helper (Renderer) Beta"
    assert name(b"", b"Google Chrome H", long_path) == "Google Chrome Helper (Renderer)"  # only the short name
    assert name(b"", b"launchd", Path("/sbin/launchd")) == "launchd"
    assert name(b"", b"kernel_task", None) == "kernel_task"


def test_cpu_percent_from_two_readings(monkeypatch):
    from datetime import timedelta

    clock = {"now": 100.0}
    monkeypatch.setattr(macos.system.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(macos.system.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))

    def process(pid, cpu_seconds, started="then"):
        return macos.system.Process(pid, "p", None, "me", 1, started, 1, timedelta(seconds=cpu_seconds))

    before = [process(1, 10), process(2, 5), process(3, 1), process(4, 2)]
    later = {1: process(1, 10.25), 2: process(2, 5.8), 4: process(4, 0, started="another")}  # 3 quit; 4 is a new one
    measured = macos.system._with_cpu(before, lambda: later, started=100.0)
    assert [found.cpu_percent for found in measured] == [50.0, 160.0, None, None]


def test_port_checks():
    with pytest.raises(ValueError, match="port must be from 1 to 65535"):
        macos.system.port_owner(0)
    with pytest.raises(ValueError, match="protocol must be"):
        macos.system.port_owner(80, "sctp")


def test_socket_list_retries_when_files_open_meanwhile():
    system = macos.system
    size = system.ctypes.sizeof(system._FDInfo)

    class Lib:
        """Has 40 descriptors, every other one a socket, though it said 1 when asked how many."""

        calls = 0

        def proc_pidinfo(self, pid, flavor, argument, buffer, buffer_size):
            self.calls += 1
            if buffer is None:
                return size
            capacity = buffer_size // size
            for index in range(min(capacity, 40)):
                buffer[index] = system._FDInfo(index, system._PROX_FDTYPE_SOCKET if index % 2 else 1)
            return min(capacity, 40) * size

    lib = Lib()
    assert system._sockets(lib, 1) == list(range(1, 40, 2))
    assert lib.calls > 2  # it came back full, and was asked again with more room


def test_paths_inside_a_folder():
    inside = macos.system._is_in
    assert inside("/Volumes/Backup/photos/a.jpg", "/Volumes/Backup") and inside("/Volumes/Backup", "/Volumes/Backup/")
    assert not inside("/Volumes/Backup 2/a.jpg", "/Volumes/Backup")
    assert inside("/Users/alice/notes.txt", "/")


def test_kill_refuses_a_pid_another_process_took(monkeypatch):
    from datetime import datetime

    system = macos.system
    then, now = datetime(2026, 10, 1, 9, 0), datetime(2026, 10, 5, 14, 30)

    def process(started, path="/usr/bin/sleep", name="sleep"):
        return system.Process(4242, name, Path(path) if path else None, "me", 1, started, None, None)

    signals = []
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system.os, "kill", lambda pid, signal: signals.append((pid, signal)))
    old = process(then)

    for current in (process(now, name="Safari"), process(None, "/Applications/Safari.app/Contents/MacOS/Safari"), None):
        monkeypatch.setattr(system, "_read_process", lambda pid, current=current: current)
        with pytest.raises(ProcessLookupError, match="has quit"):
            old.kill(force=True)  # the pid is another process's now, or nobody's
    # Another user's process: no start time to compare, but its executable tells.
    monkeypatch.setattr(system, "_read_process", lambda pid: process(None, "/bin/zsh", "zsh"))
    with pytest.raises(ProcessLookupError):
        system.kill(process(None), force=True)
    assert signals == []

    monkeypatch.setattr(system, "_read_process", lambda pid: process(then))
    old.kill()
    system.kill(4242, force=True)  # a bare pid: whatever has it now
    assert [pid for pid, _ in signals] == [4242, 4242]


def test_mount_image_detaches_and_explains_an_answer_it_cannot_read(fake_run, tmp_path):
    image = tmp_path / "Tool.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = "/dev/disk7          \tGUID_partition_scheme\n/dev/disk7s1        \tApple_HFS\t/Volumes/Tool\n"

    with pytest.raises(macos.MacOSError, match="can't be read.*detached.*GUID_partition_scheme"):
        macos.system.mount_image(image)
    assert fake_run.args == ["hdiutil", "detach", "/dev/disk7", "-force"]  # not left attached

    fake_run.stdout = '<?xml version="1.0"?><plist version="1.0"><dict><key>system-entities</key>'  # cut short
    fake_run.calls.clear()
    with pytest.raises(macos.MacOSError, match="can't be read"):
        macos.system.mount_image(image, timeout=30)
    assert [call["args"][1] for call in fake_run.calls] == ["attach"]  # no device named: nothing to detach
    assert fake_run.calls[0]["timeout"] == 30


def test_mount_image_says_when_its_cleanup_detach_failed(monkeypatch, fake_run, tmp_path):
    image = tmp_path / "Tool.dmg"
    image.write_bytes(b"dmg")
    unreadable = "/dev/disk7          \tGUID_partition_scheme\n"

    def run(args, **kwargs):
        fake_run.calls.append({"args": list(args), **kwargs})
        if args[1] == "detach":
            return subprocess.CompletedProcess(args, 16, "", "hdiutil: couldn't eject disk7 - Resource busy")
        return subprocess.CompletedProcess(args, 0, unreadable, "")

    monkeypatch.setattr(macos._system.subprocess, "run", run)
    with pytest.raises(macos.MacOSError, match="detaching /dev/disk7 failed.*Resource busy") as caught:
        macos.system.mount_image(image)
    assert "(it was detached)" not in str(caught.value)


def test_mount_image_and_updates_give_up_on_a_stuck_command(monkeypatch, fake_run, tmp_path):
    def stuck(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    image = tmp_path / "Tool.dmg"
    image.write_bytes(b"dmg")
    monkeypatch.setattr(macos._system.subprocess, "run", stuck)
    with pytest.raises(macos.CommandTimeoutError):
        macos.system.mount_image(image)
    with pytest.raises(macos.CommandTimeoutError):
        macos.system.available_updates(timeout=5)


def test_updates_whose_title_has_a_comma():
    output = (
        "* Label: ProVideoFormats-2.3\n"
        "\tTitle: Pro Video Formats, 2.3, Version: 2.3, Size: 1024KiB, Recommended: YES,\n"
        "* Label: Odd-1\n"
        "\tVersion: 1, Title: Odd: the sequel, Action: restart\n"
    )
    formats, odd = macos.system._updates(output)
    assert (formats.title, formats.version, formats.size, formats.recommended) == (
        "Pro Video Formats, 2.3", "2.3", 1024 * 1024, True
    )
    assert (odd.title, odd.version, odd.size, odd.restart) == ("Odd: the sequel", "1", None, True)


def test_model_raises_when_macos_does_not_say(fake_run):
    import json

    system = macos.system
    for answer in ("not json", json.dumps({}), json.dumps({"SPHardwareDataType": []}), json.dumps({"SPHardwareDataType": [{}]})):
        system.model.cache_clear()
        fake_run.stdout = answer
        with pytest.raises(macos.MacOSError, match="didn't tell"):
            system.model()
    system.model.cache_clear()
    fake_run.stdout = json.dumps({"SPHardwareDataType": [{"machine_name": "Mac mini"}]})
    try:
        assert system.model() == "Mac mini"
        assert fake_run.calls[-1]["timeout"] > 0
    finally:
        system.model.cache_clear()


def test_energy_usage_says_when_macos_does_not_report_it(monkeypatch):
    system = macos.system
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system, "_libproc", lambda: (None, 1.0))
    monkeypatch.setattr(system, "_pids", lambda: [1, 10])
    monkeypatch.setattr(system, "_rusage", lambda lib, pid: None)  # not even this process: unsupported
    with pytest.raises(macos.NotSupportedError, match="energy"):
        system.energy_usage(0.01)


def test_network_usage_stops_a_stuck_nettop(fake_run, monkeypatch):
    monkeypatch.setattr(macos.system, "_read_process", lambda pid: None)
    macos.system.network_usage(interval=2)
    assert fake_run.args[0] == "nettop" and fake_run.calls[-1]["timeout"] == 2 + macos.system._NETTOP_SLACK


@pytest.mark.skipif(sys.platform != "darwin", reason="loads libSystem")
def test_libsystem_is_loaded_once_with_its_signatures():
    import ctypes
    import os

    from macos import _libc

    lib = _libc.lib()
    assert lib is _libc.lib() and lib.proc_pidinfo.restype is ctypes.c_int
    assert os.getpid() in _libc.pids() and _libc.tick() > 0
    assert macos.system.memory() > 0 and 0.0 <= macos.system.memory_usage().percent <= 1.0


def test_control_center_restart_is_batched(monkeypatch):
    from macos import _system, system

    killed = []
    monkeypatch.setattr(_system, "killall", lambda name: killed.append(name))  # what restart_process runs
    system._restart_control_center()
    assert killed == ["ControlCenter"]
    with _system.batched_restarts():
        system._restart_control_center()
        system._restart_control_center()
        assert killed == ["ControlCenter"]  # put off to the end of the batch
    assert killed == ["ControlCenter", "ControlCenter"]  # once, not twice


def test_int_preferences_tolerate_hand_edited_values(monkeypatch):
    from macos import system

    assert system._as_int(2, 0) == 2 and system._as_int("3", 0) == 3 and system._as_int(True, 0) == 1
    assert system._as_int("always", 0) == 0 and system._as_int(["x"], None) is None
    stored = {"ShowDate": "sometimes"}
    monkeypatch.setattr(system.defaults, "read", lambda domain, key, default=None, **kwargs: stored.get(key, default))
    assert system.clock_format()["date"] == "auto"
    stored = {"NSStatusItemSpacing": "wide"}
    assert system.menu_bar_spacing() is None


@pytest.mark.parametrize("read, what", [("gpu_usage", "graphics processors"), ("usb_devices", "USB devices")])
def test_iokit_failing_to_list_devices_is_an_error_not_none(monkeypatch, read, what):
    """An empty iterator is "none"; IOKit refusing the query is an error, not a Mac without the devices."""
    from macos import _iokit

    class Lib:
        def IOServiceMatching(self, name):
            return 1

        def IOServiceGetMatchingServices(self, port, matching, iterator):
            return 0xE00002BC  # kIOReturnError

    monkeypatch.setattr(macos.system, "require_macos", lambda: None)
    monkeypatch.setattr(_iokit, "lib", lambda: Lib())
    with pytest.raises(macos.MacOSError, match="could not list the {} \\(IOReturn 0xe00002bc\\)".format(what)):
        getattr(macos.system, read)()


# --- Kernel buffers, built by hand -------------------------------------------------------


def _vinfo_stat(device=0, inode=0):
    """A ``vinfo_stat`` (136 bytes): the device and the inode, the rest zero."""
    import struct

    return struct.pack("=IHHQII8qqqiIIIqq", device, 0, 0, inode, 0, 0, *([0] * 8), 0, 0, 0, 0, 0, 0, 0, 0)


def _socket_fdinfo(family, kind, socket_type, local, remote, state=0):
    """
    A ``socket_fdinfo`` as ``proc_pidfdinfo`` fills it, field by field after <sys/proc_info.h>.

    ``local`` and ``remote`` are ``(address bytes, port)``: 4 bytes for IPv4, which the kernel keeps at the
    end of its 16, 16 for IPv6. The ports are in network order, as ``in_sockinfo`` holds them.
    """
    import socket
    import struct

    def in4in6(address):
        return address if len(address) == 16 else b"\x00" * 12 + address

    proc_fileinfo = struct.pack("=IIqiI", 0, 0, 0, macos.system._PROX_FDTYPE_SOCKET, 0)
    socket_info = (
        _vinfo_stat()
        + struct.pack("=QQiii", 0, 0, socket_type, 0, family)  # soi_so, soi_pcb, soi_type, soi_protocol, soi_family
        + struct.pack("=hhhhhhhHI", 0, 0, 0, 0, 0, 0, 0, 0, 0)  # the shorts, then soi_oobmark
        + struct.pack("=IIIIIhh", 0, 0, 0, 0, 0, 0, 0) * 2  # soi_rcv, soi_snd
        + struct.pack("=iI", kind, 0)  # soi_kind, rfu_1
    )
    in_sockinfo = struct.pack(
        "=iiQiiBBxxI16s16sBBxxiHhxxxx",
        socket.htons(remote[1]), socket.htons(local[1]), 0, 0, 0, 0, 0, 0, in4in6(remote[0]), in4in6(local[0]),
        0, 0, 0, 0, 0,
    )  # fmt: skip
    tcp_sockinfo = in_sockinfo + struct.pack("=i", state)
    return proc_fileinfo + socket_info + tcp_sockinfo


class _Proc:
    """A libproc whose ``proc_pidfdinfo`` hands over the buffer given for each descriptor."""

    def __init__(self, answers):
        self.answers = answers

    def proc_pidfdinfo(self, pid, fd, flavor, buffer, size):
        answer = self.answers[fd]
        if answer is None:
            return 0  # another user's process: nothing filled in
        assert len(answer) <= size
        macos.system.ctypes.memmove(buffer, answer, len(answer))
        return len(answer)


def test_socket_fields_are_read_where_the_kernel_puts_them():
    import socket

    system = macos.system
    ipv4_local, ipv4_remote = socket.inet_pton(socket.AF_INET, "192.168.0.8"), socket.inet_pton(socket.AF_INET, "142.250.79.46")
    ipv6_local, ipv6_remote = socket.inet_pton(socket.AF_INET6, "fe80::1"), socket.inet_pton(socket.AF_INET6, "2001:db8::443")
    lib = _Proc(
        {
            1: _socket_fdinfo(2, system._SOCKINFO_TCP, system._SOCK_STREAM, (ipv4_local, 54321), (ipv4_remote, 443), state=4),
            2: _socket_fdinfo(30, system._SOCKINFO_TCP, system._SOCK_STREAM, (ipv6_local, 8000), (b"\x00" * 16, 0), state=1),
            3: _socket_fdinfo(2, system._SOCKINFO_IN, system._SOCK_DGRAM, (b"\x00" * 4, 5353), (b"\x00" * 4, 0)),
            4: _socket_fdinfo(30, system._SOCKINFO_IN, system._SOCK_DGRAM, (ipv6_local, 65535), (ipv6_remote, 1)),
            5: _socket_fdinfo(1, system._SOCKINFO_IN, system._SOCK_STREAM, (b"\x00" * 4, 1), (b"\x00" * 4, 1)),  # AF_UNIX
            6: _socket_fdinfo(2, 3, system._SOCK_STREAM, (ipv4_local, 1), (ipv4_remote, 1)),  # SOCKINFO_UN
            7: _socket_fdinfo(2, system._SOCKINFO_IN, system._SOCK_STREAM, (ipv4_local, 1), (ipv4_remote, 1)),  # raw
            8: None,
        }
    )

    assert system._socket(lib, 1, 1) == system._Socket("tcp", "192.168.0.8", 54321, "142.250.79.46", 443, "established")
    assert system._socket(lib, 1, 2) == system._Socket("tcp", "fe80::1", 8000, "::", 0, "listen")
    assert system._socket(lib, 1, 3) == system._Socket("udp", "0.0.0.0", 5353, "0.0.0.0", 0, None)
    assert system._socket(lib, 1, 4) == system._Socket("udp", "fe80::1", 65535, "2001:db8::443", 1, None)
    assert [system._socket(lib, 1, fd) for fd in (5, 6, 7, 8)] == [None] * 4


def test_vnode_paths_are_read_after_the_vnode_info():
    import struct

    system = macos.system
    name = b"/Users/me/caf\xe9.txt"  # Latin-1 bytes in a name, as the file system may hold them
    info = _vinfo_stat(device=16777234, inode=2 ** 40 + 5) + bytes(system._VNODE_INFO - 136) + name + b"\x00"
    found = system._vnode(b"\xff" * 24 + info, 24)  # after a proc_fileinfo
    assert found == system._Opened("/Users/me/caf\udce9.txt", (16777234, 2 ** 40 + 5))
    assert found.path.encode("utf-8", "surrogateescape") == name  # os.fsdecode: the bytes survive

    longest = b"/" + b"x" * (system._MAXPATHLEN - 1)  # fills vip_path with no NUL after it
    found = system._vnode(_vinfo_stat() + bytes(system._VNODE_INFO - 136) + longest + b"\xaa" * 8, 0)
    assert found.path == longest.decode() and found.file == (0, 0)
    assert struct.calcsize("=IHHQ") == 16  # the device and the inode sit in the first 16 bytes of a vinfo_stat


def test_open_files_are_read_from_the_descriptors_the_folders_and_the_executable():
    system = macos.system
    ctypes = system.ctypes

    def vnode_info_path(device, inode, path):
        return _vinfo_stat(device, inode) + bytes(system._VNODE_INFO - 136) + path.ljust(system._MAXPATHLEN, b"\x00")

    descriptors = [(3, system._PROX_FDTYPE_VNODE), (4, system._PROX_FDTYPE_SOCKET), (5, system._PROX_FDTYPE_VNODE), (6, 1)]
    files = {
        3: bytes(system._SOCKET) + vnode_info_path(1, 100, b"/tmp/a.log"),
        5: bytes(system._SOCKET) + vnode_info_path(1, 101, b""),  # a vnode without a path (a pipe...): dropped
        6: bytes(system._SOCKET) + vnode_info_path(2, 7, b"/Volumes/Backup"),
    }
    folders = vnode_info_path(1, 200, b"/Users/me/project") + vnode_info_path(1, 2, b"/")  # pvi_cdir, pvi_rdir

    class Lib(_Proc):
        def proc_pidinfo(self, pid, flavor, argument, buffer, size):
            if flavor == system._PROC_PIDLISTFDS:
                if buffer is None:
                    return len(descriptors) * ctypes.sizeof(system._FDInfo)
                for index, (fd, kind) in enumerate(descriptors):
                    buffer[index] = system._FDInfo(fd, kind)
                return len(descriptors) * ctypes.sizeof(system._FDInfo)
            assert flavor == system._PROC_PIDVNODEPATHINFO and size == system._FOLDERS_INFO_SIZE
            ctypes.memmove(buffer, folders, len(folders))
            return len(folders)

        def proc_pidpath(self, pid, buffer, size):
            buffer.value = b"/usr/bin/python3"
            return len(buffer.value)

    assert system._files(Lib(files), 42) == [
        system._Opened("/tmp/a.log", (1, 100)),
        system._Opened("/Volumes/Backup", (2, 7)),
        system._Opened("/Users/me/project", (1, 200)),  # the working folder, not the root
        system._Opened("/usr/bin/python3", None),
    ]


# --- Parsing what the commands answer ------------------------------------------------------


def test_update_fields_start_only_at_known_names():
    fields = macos.system._update_fields(
        "Title: Command Line Tools for Xcode, 26.1, Version: 26.1, Size: 900KiB, Recommended: NO, Action: none, Build: 17B55,"
    )
    assert fields == {
        "Title": "Command Line Tools for Xcode, 26.1", "Version": "26.1", "Size": "900KiB",
        "Recommended": "NO", "Action": "none", "Build": "17B55",
    }  # fmt: skip
    # A field's name inside a value ("MyVersion:") doesn't start a field: it isn't after a comma.
    assert macos.system._update_fields("Title: MyVersion: Pro, Version: 2") == {"Title": "MyVersion: Pro", "Version": "2"}
    assert macos.system._update_fields("") == {}
    assert macos.system._update_fields("no fields here") == {}


def test_updates_without_a_size_or_a_restart():
    output = (
        "Software Update found the following new or updated software:\n"
        "* Label: Résumé Helper-1.0\n"
        "\tTitle: R\xe9sum\xe9\xa0Helper, Version: 1.0, Size: about 3MB, Recommended: no, Action: shut down,\n"
        "* Label: Bare-2\n"
        "\tSize: 10KiB\n"
    )
    helper, bare = macos.system._updates(output)
    assert helper == macos.system.Update("Résumé Helper-1.0", "Résumé Helper", "1.0", None, False, False)
    # Fields missing: the title is the label, the version empty.
    assert bare == macos.system.Update("Bare-2", "Bare-2", "", 10 * 1024, False, False)
    assert macos.system._updates("") == []


def test_nettop_rows_skip_lines_that_are_not_a_process():
    output = (
        "time,,bytes_in,bytes_out,\n"
        "00:05:00.63,com.apple.WebKit.Networking.412,10,20,\n"  # dots in the name: the pid is after the last one
        "00:05:00.63,Caf\xe9 ☕.77,1,2,\n"
        "00:05:00.63,nopid,1,2,\n"  # no pid
        "00:05:00.63,launchd.x1,1,2,\n"  # a pid that isn't a number
        "00:05:00.63,.9,1,2,\n"  # no name
        "00:05:00.63,mds.88,-,2,\n"  # a count that isn't one
        "short,\n"
        "\n"
    )
    assert macos.system._nettop_rows(output) == [(412, "com.apple.WebKit.Networking", 10, 20), (77, "Caf\xe9 ☕", 1, 2)]
    assert macos.system._nettop_rows("syslogd.375,0,43115,\n") == []  # no header: not a sample
    assert macos.system._nettop_rows("time,,bytes_in,bytes_out,\n") == []


def _ips(path, header, body=None):
    import json

    path.write_text(json.dumps(header) + "\n" + (body if isinstance(body, str) else json.dumps(body or {})), encoding="utf-8")
    return path


_CRASH = {"app_name": "Safari", "app_version": "18.6", "bug_type": "309", "timestamp": "2026-09-29 13:55:00.12 -0300"}


def test_crash_report_reads_the_header_and_the_body(tmp_path):
    from datetime import timedelta, timezone

    path = _ips(tmp_path / "Safari-1.ips", _CRASH, {"exception": {"type": "EXC_BAD_ACCESS", "signal": "SIGSEGV"}})
    report = macos.system._crash_report(path)
    assert report == macos.system.CrashReport(
        app="Safari",
        version="18.6",
        date=datetime(2026, 9, 29, 13, 55, 0, 120000, tzinfo=timezone(timedelta(hours=-3))),
        reason="EXC_BAD_ACCESS (SIGSEGV)",
        path=path,
    )
    # The old format's bug_type, as a number; an exception with no signal.
    path = _ips(tmp_path / "old.ips", dict(_CRASH, bug_type=109), {"exception": {"type": "EXC_CRASH"}})
    assert macos.system._crash_report(path).reason == "EXC_CRASH"


def test_crash_report_keeps_what_it_can_of_a_broken_report(tmp_path):
    # A body that isn't JSON (cut short as it was written) and a timestamp in another shape: the rest is kept.
    path = _ips(tmp_path / "Mail.ips", dict(_CRASH, app_name="Mail", timestamp="yesterday", app_version=""), '{"exception": {')
    assert macos.system._crash_report(path) == macos.system.CrashReport("Mail", None, None, None, path)
    # A signal without an exception type: what ended it comes from the termination instead.
    body = {"exception": {"signal": "SIGABRT"}, "termination": {"indicator": "Abort trap: 6"}}
    path = _ips(tmp_path / "x.ips", dict(_CRASH), body)
    assert macos.system._crash_report(path).reason == "Abort trap: 6"


def test_crash_report_names_the_app_from_whatever_says_it(tmp_path):
    header = {"bug_type": "309"}
    assert macos.system._crash_report(_ips(tmp_path / "a.ips", dict(header, name="mdworker"))).app == "mdworker"
    assert macos.system._crash_report(_ips(tmp_path / "b.ips", header, {"procName": "bird"})).app == "bird"
    assert macos.system._crash_report(_ips(tmp_path / "Finder-2026.ips", header)).app == "Finder-2026"  # the file's name


def test_crash_report_skips_other_reports(tmp_path):
    assert macos.system._crash_report(_ips(tmp_path / "a.ips", dict(_CRASH, bug_type="211"))) is None  # analytics
    assert macos.system._crash_report(_ips(tmp_path / "b.ips", dict(_CRASH)), app="Notes") is None  # another app's
    assert macos.system._crash_report(_ips(tmp_path / "c.ips", dict(_CRASH)), app="SAFARI").app == "Safari"
    (tmp_path / "empty.ips").write_text("")
    assert macos.system._crash_report(tmp_path / "empty.ips") is None
    (tmp_path / "binary.ips").write_bytes(b"\xff\xfe\x00garbage\n")
    assert macos.system._crash_report(tmp_path / "binary.ips") is None
    assert macos.system._crash_report(tmp_path / "missing.ips") is None
    (tmp_path / "string.ips").write_text('"309"\n{}')
    assert macos.system._crash_report(tmp_path / "string.ips") is None  # a header that isn't an object


@pytest.fixture
def tokyo(monkeypatch):
    """This Mac's clock set to Tokyo (UTC+9, no daylight saving): local times are known in advance."""
    import time

    if not hasattr(time, "tzset"):
        pytest.skip("needs time.tzset")
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_crash_dates_compared_on_the_local_clock_without_a_zone(tokyo):
    from datetime import timedelta, timezone

    crashed = datetime(2026, 9, 29, 13, 55, tzinfo=timezone(timedelta(hours=-3)))  # 16:55 UTC, 01:55 the 30th in Tokyo
    assert macos.system._before(crashed, datetime(2026, 9, 30, 2, 0))
    assert not macos.system._before(crashed, datetime(2026, 9, 30, 1, 0))
    assert not macos.system._before(crashed, datetime(2026, 9, 29, 14, 0))  # the report's own clock isn't the Mac's
    # A cutoff with a zone is compared as an instant, whatever the Mac's clock.
    assert macos.system._before(crashed, datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc))
    assert not macos.system._before(crashed, datetime(2026, 9, 29, 13, 55, tzinfo=timezone(timedelta(hours=-3))))


def test_crash_reports_skip_an_unreadable_folder_and_list_undated_ones_last(tmp_path, monkeypatch):
    readable, unreadable = tmp_path / "mine", tmp_path / "system"
    readable.mkdir()
    _ips(readable / "dated.ips", dict(_CRASH, app_name="Dated"))
    _ips(readable / "undated.ips", dict(_CRASH, app_name="Undated", timestamp=""))
    real_glob = Path.glob

    def glob(self, pattern):
        if self == unreadable:
            raise PermissionError(13, "Permission denied", str(self))
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", glob)
    monkeypatch.setattr(macos.system, "_REPORT_FOLDERS", (str(unreadable), str(readable)))
    monkeypatch.setattr(macos.system, "require_macos", lambda: None)
    assert [crash.app for crash in macos.system.crash_reports()] == ["Dated", "Undated"]
    # With a cutoff, a report without a date is kept: when it crashed isn't known.
    assert [crash.app for crash in macos.system.crash_reports(since=datetime(2027, 1, 1))] == ["Undated"]


def test_log_entry_from_log_shows_ndjson():
    import json
    from datetime import timedelta, timezone

    line = json.dumps(
        {
            "traceID": 1, "eventType": "logEvent", "timestamp": "2026-10-13 09:41:05.123456-0300",
            "processImagePath": "/usr/sbin/bluetoothd", "processID": 123, "subsystem": "com.apple.bluetooth",
            "category": "Server", "messageType": "Fault", "eventMessage": "Ação 💡 <private>", "timezoneName": "",
        }
    )  # fmt: skip
    entry = macos.system._log_entry(line)
    assert entry == macos.system.LogEntry(
        date=datetime(2026, 10, 13, 9, 41, 5, 123456, tzinfo=timezone(timedelta(hours=-3))),
        process="bluetoothd",
        pid=123,
        subsystem="com.apple.bluetooth",
        category="Server",
        level="fault",
        message="Ação 💡 <private>",
    )


def test_log_entry_with_fields_missing_or_empty():
    import json

    entry = macos.system._log_entry(
        json.dumps({"eventType": "logEvent", "processID": -1, "subsystem": "", "category": None, "eventMessage": None})
    )
    assert entry == macos.system.LogEntry(None, "?", None, None, None, "default", "")
    assert macos.system._log_entry('{"eventType": "logEvent", "timestamp": "2026-10-13"}').date is None  # no time
    assert macos.system._log_entry('{"eventType": "logEvent", "eventMessage": "cut') is None  # a line cut short
    assert macos.system._log_entry("") is None
    assert macos.system._log_entry('{"count": 12, "finished": 1}') is None  # log show's last line: no event


def test_launchd_state_of_one_job(fake_run):
    fake_run.stdout = "gui/501/com.example.job = {\n\tactive count = 1\n\tstate = running\n\tprogram = /bin/sleep\n}\n"
    assert macos.system._launchd_state("gui/501", "com.example.job") is True
    assert fake_run.args == ["launchctl", "print", "gui/501/com.example.job"]
    fake_run.stdout = "gui/501/com.example.job = {\n\tstate = not running\n}\n"
    assert macos.system._launchd_state("gui/501", "com.example.job") is False
    fake_run.returncode, fake_run.stdout = 113, ""
    fake_run.stderr = 'Bad request.\nCould not find service "com.example.job" in domain for user gui: 501\n'
    assert macos.system._launchd_state("gui/501", "com.example.job") is False  # not loaded: not running
    fake_run.stderr = "Operation not permitted\n"
    assert macos.system._launchd_state("system", "com.example.job") is None  # launchd won't say


def test_launchd_running_keeps_odd_lines_for_asking_alone(fake_run):
    fake_run.stdout = (
        "system = {\n\tservices = {\n"
        "\t\t     123      - \tcom.example.up\n"
        "\t\t       -     78 \tcom.example.odd\n"  # no pid column as expected: asked alone later
        "\t\tcom.example.bare\n"
        "\t}\n}\n"
    )
    listed = macos.system._launchd_running("system")
    assert listed == {"com.example.up": True, "com.example.odd": None, "com.example.bare": None}
    fake_run.stdout = "system = {\n\tservices = {\n\t}\n}\n"
    assert macos.system._launchd_running("system") == {}  # nothing loaded, rather than nothing known
    fake_run.returncode, fake_run.stderr = 1, "Operation not permitted\n"
    assert macos.system._launchd_running("system") is None


def test_running_state_asks_alone_only_what_the_listing_didnt_say(monkeypatch):
    asked = []
    monkeypatch.setattr(macos.system, "_launchd_state", lambda domain, label: asked.append(label) or True)
    listed = {"com.example.up": True, "com.example.down": False, "com.example.odd": None}
    assert macos.system._running_state(listed, "gui/501", "com.example.up") is True
    assert macos.system._running_state(listed, "gui/501", "com.example.down") is False
    assert macos.system._running_state(listed, "gui/501", "com.example.unloaded") is False  # not listed: not loaded
    assert asked == []
    assert macos.system._running_state(listed, "gui/501", "com.example.odd") is True
    assert asked == ["com.example.odd"]


_PLIST = '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0">{}</plist>'


def test_mount_image_takes_the_first_volume_and_skips_odd_entities(fake_run, tmp_path):
    image = tmp_path / "Two.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = _PLIST.format(
        "<dict><key>system-entities</key><array><string>junk</string>"
        "<dict><key>mount-point</key><string></string></dict>"  # an empty mount point is no volume
        "<dict><key>mount-point</key><string>/Volumes/Två</string></dict>"
        "<dict><key>mount-point</key><string>/Volumes/Two 1</string></dict></array></dict>"
    )
    assert macos.system.mount_image(image) == Path("/Volumes/Två")
    assert len(fake_run.calls) == 1  # nothing detached


@pytest.mark.parametrize(
    "answer",
    [
        _PLIST.format("<array><string>/dev/disk5</string></array>"),  # a plist, but not the dictionary expected
        _PLIST.format("<dict><key>system-entities</key><string>/dev/disk5</string></dict>"),
        "/dev/disk5s1 \tApple_HFS\t/Volumes/Tool\n/dev/disk5 \tGUID_partition_scheme\n" + _PLIST.format("<dict>"),
    ],
)
def test_mount_image_detaches_the_whole_disk_its_odd_answer_names(fake_run, tmp_path, answer):
    image = tmp_path / "Tool.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = answer
    with pytest.raises(macos.MacOSError, match=r"can't be read \(it was detached\)"):
        macos.system.mount_image(image)
    assert fake_run.args == ["hdiutil", "detach", "/dev/disk5", "-force"]  # the shortest name: the whole disk


def test_mount_image_without_entities_detaches_nothing(fake_run, tmp_path):
    image = tmp_path / "Empty.dmg"
    image.write_bytes(b"dmg")
    fake_run.stdout = _PLIST.format("<dict><key>system-entities</key><array/></dict>")
    with pytest.raises(macos.MacOSError, match=r"no volume to mount$"):
        macos.system.mount_image(image)
    assert [call["args"][1] for call in fake_run.calls] == ["attach"]
