"""Unit tests for the speed test, network and energy use, the GPU and disk health."""

import sys
from pathlib import Path

import pytest

import macos
from macos import network, system

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="reads this Mac's real counters")


def test_speed_test(fake_run):
    fake_run.stdout = (Path(__file__).parent / "networkquality.json").read_text()
    result = network.speed_test(sequential=True)
    assert fake_run.args == ["networkQuality", "-c", "-s"]
    assert result == network.SpeedTest(
        download=43.61,  # bits per second, as networkQuality's own summary shows in Mbps
        upload=39.42,
        latency=54.6,
        loaded_latency=1126.6,  # 60,000 ms / 53.3 RPM
        responsiveness=53.3,
        interface="en0",
        server="brsao4-edge-bx-022.aaplimg.com",
    )
    fake_run.stdout = "not json"
    with pytest.raises(macos.MacOSError, match="isn't JSON"):
        network.speed_test()


@pytest.mark.parametrize(
    "output",
    [
        ",bytes_in,bytes_out,\nsyslogd.375,0,43115,\nGoogle Chrome H.30216,3080,3446,\n",  # from a terminal
        "time,,bytes_in,bytes_out,\n00:05:00.63,syslogd.375,0,43115,\n00:05:00.63,Google Chrome H.30216,3080,3446,\n",
    ],
)
def test_nettop_rows(output):
    assert system._nettop_rows(output) == [(375, "syslogd", 0, 43115), (30216, "Google Chrome H", 3080, 3446)]


def test_nettop_rows_take_the_last_sample():
    output = ",bytes_in,bytes_out,\napsd.381,4224,5682,\n,bytes_in,bytes_out,\napsd.381,12,0,\n"
    assert system._nettop_rows(output) == [(381, "apsd", 12, 0)]  # the deltas, with -d
    assert system._nettop_rows("") == []


def test_disk_health(monkeypatch):
    import plistlib

    answers = {
        ("list",): {"WholeDisks": ["disk0", "disk4"]},
        ("info", "disk0"): {
            "MediaName": "APPLE SSD", "Size": 500, "Internal": True, "SolidState": True, "SMARTStatus": "Verified"
        },
        ("info", "disk4"): {"MediaName": "USB Drive ", "Size": 64, "Internal": False, "SMARTStatus": "Not Supported"},
    }
    monkeypatch.setattr(system, "require_macos", lambda: None)

    def diskutil(args, **kwargs):
        return plistlib.dumps(answers[(args[1],) if args[1] == "list" else (args[1], args[3])]).decode()

    monkeypatch.setattr(system, "_run", diskutil)
    assert system.disk_health() == [
        system.DiskHealth("disk0", "APPLE SSD", 500, True, True, "verified"),
        system.DiskHealth("disk4", "USB Drive", 64, False, None, None),
    ]


def test_argument_checks():
    with pytest.raises(ValueError, match="interval must be positive"):
        system.network_usage(interval=0)
    with pytest.raises(ValueError, match="interval must be positive"):
        system.energy_usage(0)


@darwin
def test_network_usage_sees_every_process():
    found = system.network_usage()
    assert found and all(use.received >= 0 and use.sent >= 0 and use.pid > 0 for use in found)
    assert found == sorted(found, key=lambda use: use.received + use.sent, reverse=True) or len(found) == 1


@darwin
def test_energy_usage_of_a_busy_process():
    import subprocess

    busy = subprocess.Popen([sys.executable, "-c", "while True: pass"])
    try:
        found = system.energy_usage(0.5)
        mine = next(use for use in found if use.pid == busy.pid)
        assert mine.watts >= 0 and mine.disk_read >= 0 and mine.disk_written >= 0
        if any(use.watts for use in found):  # Apple silicon measures power; Intel and some VMs don't
            assert mine.watts > 0.1
    finally:
        busy.kill()


@darwin
def test_gpu_and_disks():
    for gpu in system.gpu_usage():  # a VM may have none
        assert 0 <= gpu.percent <= 100 and gpu.name
    disks = system.disk_health()
    assert disks and all(disk.device.startswith("disk") and disk.size > 0 for disk in disks)
    assert all(disk.smart in ("verified", "failing", None) for disk in disks)


def test_energy_usage_skips_a_pid_taken_by_a_new_process(monkeypatch):
    from datetime import timedelta

    readings = {  # pid: (before, after) as (nanojoules, bytes read, bytes written, start)
        10: ((1_000_000_000, 0, 0, 5), (3_000_000_000, 4096, 0, 5)),  # the same process: 2 J over the second
        11: ((1_000_000_000, 0, 0, 5), (9_000_000_000, 0, 0, 7)),  # quit, and a new one took pid 11
    }
    calls = {}

    def rusage(lib, pid):
        calls[pid] = calls.get(pid, -1) + 1
        return readings[pid][calls[pid]]

    clock = {"now": 0.0}
    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(system, "_libproc", lambda: (None, 1.0))
    monkeypatch.setattr(system, "_rusage", rusage)
    monkeypatch.setattr(system, "_pids", lambda: [10, 11])
    monkeypatch.setattr(system.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(system.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))
    monkeypatch.setattr(
        system, "_read_process", lambda pid: system.Process(pid, "p{}".format(pid), None, "me", 1, None, 1, timedelta(0))
    )
    assert system.energy_usage(1.0) == [system.EnergyUsage(10, "p10", 2.0, 4096, 0)]
