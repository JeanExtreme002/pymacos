"""Tests of :mod:`macos.system` against the real system. Skipped outside macOS."""

import uuid
from pathlib import Path

import pytest

import macos


def test_fonts():
    families = macos.system.fonts()

    assert "Helvetica" in families
    assert families == sorted(families, key=str.casefold)
    assert not any(name.startswith(".") for name in families)


def test_system_info():
    import re
    from datetime import timedelta

    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", macos.system.version())
    assert macos.system.build()
    assert macos.system.model()
    assert re.fullmatch(r"[A-Za-z]+\d+,\d+", macos.system.model_identifier())
    assert macos.system.processor()
    assert macos.system.memory() >= 2**30
    assert macos.system.computer_name()
    assert macos.system.uptime() > timedelta(0)
    assert macos.system.idle_time() >= timedelta(0)


def test_volumes_and_eject(tmp_path):
    import subprocess

    volumes = macos.system.volumes()
    assert volumes[0].path == Path("/") and volumes[0].total > 0

    name = "PymacosTest{}".format(uuid.uuid4().hex[:6])
    image = tmp_path / "test.dmg"
    created = subprocess.run(
        ["hdiutil", "create", "-size", "2m", "-fs", "HFS+", "-volname", name, "-o", str(image), "-quiet"]
    )
    if created.returncode != 0 or subprocess.run(["hdiutil", "attach", str(image), "-quiet"]).returncode != 0:
        pytest.skip("hdiutil can't create or attach disk images here")
    try:
        mounted = [volume for volume in macos.system.volumes() if volume.name == name]
        assert mounted and mounted[0].is_ejectable
        macos.system.eject(name)
        assert name not in [volume.name for volume in macos.system.volumes()]
    finally:
        subprocess.run(["hdiutil", "detach", "/Volumes/{}".format(name), "-quiet"], capture_output=True)


def test_thermal_state_and_lid():
    assert macos.system.thermal_state() in ("nominal", "fair", "serious", "critical")
    try:
        assert isinstance(macos.system.lid_closed(), bool)
    except macos.NotSupportedError:
        pass  # a desktop Mac


def test_camera_microphone_and_power_state():
    assert isinstance(macos.system.camera_in_use(), bool)
    assert isinstance(macos.system.microphone_in_use(), bool)
    assert isinstance(macos.power.low_power_mode(), bool)
    assert isinstance(macos.keyboard.caps_lock(), bool)


def test_wait_for_idle():
    assert macos.system.wait_for_idle(0) is True
    assert macos.system.wait_for_idle(3600, timeout=0.3) is False


def test_cpu_and_memory_usage():
    assert 0.0 <= macos.system.cpu_usage(0.3) <= 1.0
    usage = macos.system.memory_usage()
    assert usage.total == macos.system.memory() and 0 < usage.used <= usage.total
    assert 0.0 < usage.percent <= 1.0 and usage.wired > 0


def test_mount_image(tmp_path):
    import subprocess

    folder = tmp_path / "content"
    folder.mkdir()
    (folder / "hello.txt").write_text("hi")
    image = tmp_path / "test.dmg"
    subprocess.run(["hdiutil", "create", "-quiet", "-volname", "PymacosTest", "-srcfolder", str(folder), str(image)], check=True)

    mounted = macos.system.mount_image(image)
    try:
        assert (mounted / "hello.txt").read_text() == "hi"
    finally:
        macos.system.unmount_image(mounted, force=True)
    assert not mounted.exists()


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


def test_who_uses_a_file_by_any_of_its_names(tmp_path):
    import os

    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    first.write_text("same file")
    os.link(first, second)  # two names for one file
    with open(first):
        assert any(user.pid == os.getpid() for user in macos.system.who_uses(second))
    assert not any(user.pid == os.getpid() for user in macos.system.who_uses(second))


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


def test_logs():
    found = macos.system.logs(last="2m", limit=5)
    assert len(found) <= 5 and all(entry.process and entry.level for entry in found)
    assert all(entry.level in ("error", "fault") for entry in macos.system.logs(level="error", last="5m", limit=5))


def test_network_usage_sees_every_process():
    found = macos.system.network_usage()
    assert found and all(use.received >= 0 and use.sent >= 0 and use.pid > 0 for use in found)
    assert found == sorted(found, key=lambda use: use.received + use.sent, reverse=True) or len(found) == 1


def test_energy_usage_of_a_busy_process():
    import subprocess
    import sys

    busy = subprocess.Popen([sys.executable, "-c", "while True: pass"])
    try:
        found = macos.system.energy_usage(0.5)
        mine = next(use for use in found if use.pid == busy.pid)
        assert mine.watts >= 0 and mine.disk_read >= 0 and mine.disk_written >= 0
        if any(use.watts for use in found):  # Apple silicon measures power; Intel and some VMs don't
            assert mine.watts > 0.1
    finally:
        busy.kill()


def test_gpu_and_disks():
    for gpu in macos.system.gpu_usage():  # a VM may have none
        assert 0 <= gpu.percent <= 100 and gpu.name
    disks = macos.system.disk_health()
    assert disks and all(disk.device.startswith("disk") and disk.size > 0 for disk in disks)
    assert all(disk.smart in ("verified", "failing", None) for disk in disks)
