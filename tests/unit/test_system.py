"""Unit tests for :mod:`macos.system`. They run on any platform."""

import subprocess
import sys
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
    with pytest.raises(FileNotFoundError):
        macos.system.mount_image(tmp_path / "missing.dmg")


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


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real processes")
def test_processes():
    import os
    import subprocess

    found = macos.system.processes()
    own = next(process for process in found if process.pid == os.getpid())
    assert own.memory and own.cpu_time is not None and own.started and own.path and own.path.exists()
    assert any(process.pid == 1 and process.name == "launchd" and process.user == "root" for process in found)
    assert macos.system.process(os.getpid()).parent_pid == os.getppid()

    child = subprocess.Popen(["sleep", "30"])
    try:
        assert macos.system.process(child.pid).name == "sleep"
        assert macos.system.process(child.pid, cpu=True).cpu_percent is not None
        macos.system.process(child.pid).kill()
        assert child.wait(timeout=5) == -15
    finally:
        child.kill()
    assert macos.system.process(child.pid) is None
    with pytest.raises(ProcessLookupError):
        macos.system.kill(child.pid)


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


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real sockets")
def test_ports_and_their_owners():
    import os
    import socket

    with socket.socket() as server, socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as udp:
        server.bind(("127.0.0.1", 0))
        server.listen()
        udp.bind(("::1", 0))
        tcp_port, udp_port = server.getsockname()[1], udp.getsockname()[1]
        found = macos.system.ports()
        assert macos.system.Port(tcp_port, "tcp", "127.0.0.1", os.getpid(), macos.system.process(os.getpid()).name) in found
        assert any(port.port == udp_port and port.protocol == "udp" and port.address == "::1" for port in found)
        assert macos.system.port_owner(tcp_port).pid == os.getpid()
        assert macos.system.port_owner(udp_port, "udp").pid == os.getpid()
        assert macos.system.port_owner(tcp_port, "udp") is None
    assert macos.system.port_owner(tcp_port) is None  # closed


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


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real sockets")
def test_connections():
    import os
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port)) as client, server.accept()[0]:
            local = client.getsockname()[1]
            mine = [found for found in macos.system.connections() if found.pid == os.getpid()]
            assert macos.system.Connection(
                "tcp", "127.0.0.1", local, "127.0.0.1", port, "established", os.getpid(), mine[0].process
            ) in mine
            assert any(found.local_port == port and found.remote_port == local for found in mine)  # the server's end
            assert not any(found.state == "listen" for found in mine)  # servers are in ports()


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real open files")
def test_open_files_and_who_uses(tmp_path):
    import os

    held = tmp_path / "held.txt"
    with open(held, "w"):
        assert any(user.pid == os.getpid() for user in macos.system.who_uses(held))
        assert any(user.pid == os.getpid() for user in macos.system.who_uses(tmp_path))  # a file inside counts
        assert Path(os.path.realpath(held)) in macos.system.open_files(os.getpid())
    assert not any(user.pid == os.getpid() for user in macos.system.who_uses(held))
    assert Path(os.path.realpath(os.getcwd())) in macos.system.open_files(os.getpid())
    with pytest.raises(FileNotFoundError):
        macos.system.who_uses(tmp_path / "missing")


def test_paths_inside_a_folder():
    inside = macos.system._is_in
    assert inside("/Volumes/Backup/photos/a.jpg", "/Volumes/Backup") and inside("/Volumes/Backup", "/Volumes/Backup/")
    assert not inside("/Volumes/Backup 2/a.jpg", "/Volumes/Backup")
    assert inside("/Users/alice/notes.txt", "/")


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real open files")
def test_who_uses_a_file_by_any_of_its_names(tmp_path):
    import os

    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_text("same file")
    os.link(first, second)  # two names for one file
    with open(first):
        assert any(user.pid == os.getpid() for user in macos.system.who_uses(second))
    assert not any(user.pid == os.getpid() for user in macos.system.who_uses(second))


@pytest.mark.skipif(sys.platform != "darwin", reason="reads the real sockets")
def test_a_connected_udp_socket_over_ipv6():
    import os
    import socket

    if not socket.has_ipv6:
        pytest.skip("no IPv6 here")
    udp = (socket.AF_INET6, socket.SOCK_DGRAM)
    with socket.socket(*udp) as receiver, socket.socket(*udp) as sender:
        try:
            receiver.bind(("::1", 0))
            sender.connect(("::1", receiver.getsockname()[1]))
        except OSError:
            pytest.skip("no IPv6 loopback here")
        local, remote = sender.getsockname()[1], receiver.getsockname()[1]
        found = [c for c in macos.system.connections() if c.pid == os.getpid() and c.protocol == "udp"]
        assert any(
            c.local_port == local and c.remote_address == "::1" and c.remote_port == remote and c.state is None for c in found
        )
        listening = [p.port for p in macos.system.ports() if p.pid == os.getpid() and p.protocol == "udp"]
        assert remote in listening and local not in listening  # connected: a client, not a listener


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
