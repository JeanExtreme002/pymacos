"""Unit tests for the Wi-Fi signal, installed apps, crash reports and the system log."""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

import macos
from macos import apps, network, system

darwin = pytest.mark.skipif(sys.platform != "darwin", reason="reads this Mac's own state")


def test_wifi_quality():
    signal = network.WiFiSignal(-62, -95, 866.0, 157, "5GHz", 80, "wpa2_personal")
    assert (signal.snr, signal.quality) == (33, "good")
    assert network.WiFiSignal(-50, -90, 1, None, None, None, None).quality == "excellent"
    assert network.WiFiSignal(-72, -90, 1, None, None, None, None).quality == "fair"
    assert network.WiFiSignal(-83, -95, 1, None, None, None, None).quality == "poor"


@darwin
def test_wifi_signal():
    signal = network.wifi_signal()
    if signal is not None:  # None on a Mac off Wi-Fi, as CI's
        assert signal.rssi < 0 and signal.transmit_rate > 0 and signal.band in ("2.4GHz", "5GHz", "6GHz", None)


def test_installed_app_from_its_info(tmp_path):
    import plistlib

    bundle = tmp_path / "Tool.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleName": "Tool", "CFBundleIdentifier": "com.example.tool", "CFBundleShortVersionString": "2.1"})
    )
    assert apps._installed_app(str(bundle)) == apps.InstalledApp("Tool", "com.example.tool", "2.1", bundle)
    assert apps._installed_app(str(tmp_path / "Broken.app")) is None


@darwin
def test_installed():
    found = apps.installed()
    assert any(app.bundle_id == "com.apple.calculator" and app.version for app in found)
    assert all(app.path.suffix == ".app" for app in found)


def _report(folder, name, header, body):
    (folder / name).write_text(json.dumps(header) + "\n" + json.dumps(body))


def test_crash_reports(tmp_path, monkeypatch):
    safari = {"app_name": "Safari", "app_version": "18.6", "bug_type": "309", "timestamp": "2026-09-29 13:55:00.00 -0300"}
    _report(tmp_path, "Safari-1.ips", safari, {"exception": {"type": "EXC_BAD_ACCESS", "signal": "SIGSEGV"}})
    notes = {"app_name": "Notes", "bug_type": "309", "timestamp": "2026-09-20 08:00:00.00 -0300"}
    _report(tmp_path, "Notes-1.ips", notes, {"termination": {"indicator": "Abort trap: 6"}})
    _report(tmp_path, "analytics.ips", {"bug_type": "211", "timestamp": "2026-09-29 13:00:00.00 -0300"}, {})
    (tmp_path / "broken.ips").write_text("not json")
    monkeypatch.setattr(system, "_REPORT_FOLDERS", (str(tmp_path),))
    monkeypatch.setattr(system, "require_macos", lambda: None)

    found = system.crash_reports()
    assert [(crash.app, crash.version, crash.reason) for crash in found] == [
        ("Safari", "18.6", "EXC_BAD_ACCESS (SIGSEGV)"),  # the latest first
        ("Notes", None, "Abort trap: 6"),
    ]
    assert [crash.app for crash in system.crash_reports("safari")] == ["Safari"]
    assert [crash.app for crash in system.crash_reports(since=datetime(2026, 9, 25))] == ["Safari"]


def test_crash_reports_read_only_the_header_of_other_apps_reports(tmp_path, monkeypatch):
    import builtins

    header = {"app_name": "Notes", "bug_type": "309", "timestamp": "2026-09-20 08:00:00.00 -0300"}
    _report(tmp_path, "Notes-1.ips", header, {"exception": {"type": "EXC_CRASH"}})
    _report(tmp_path, "Safari-1.ips", dict(header, app_name="Safari"), {"exception": {"type": "EXC_BAD_ACCESS"}})
    monkeypatch.setattr(system, "_REPORT_FOLDERS", (str(tmp_path),))
    monkeypatch.setattr(system, "require_macos", lambda: None)
    bodies = []
    real_open = builtins.open

    class Counting:
        def __init__(self, file):
            self.file = file

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.file.close()

        def readline(self):
            return self.file.readline()

        def read(self):
            bodies.append(self.file.name)
            return self.file.read()

    monkeypatch.setattr(builtins, "open", lambda path, *args, **kwargs: Counting(real_open(path, *args, **kwargs)))
    assert [crash.reason for crash in system.crash_reports("notes")] == ["EXC_CRASH"]
    assert [Path(name).name for name in bodies] == ["Notes-1.ips"]  # Safari's body was never read


def test_log_entries_and_predicates():
    event = {
        "eventType": "logEvent",
        "timestamp": "2026-09-30 01:31:10.723597-0300",
        "processImagePath": "/Applications/Safari.app/Contents/MacOS/Safari",
        "processID": "612",
        "subsystem": "com.apple.WebKit",
        "category": "Loading",
        "messageType": "Error",
        "eventMessage": "failed",
    }
    entry = system._log_entry(json.dumps(event))
    assert (entry.process, entry.pid, entry.subsystem, entry.level, entry.message) == (
        "Safari", 612, "com.apple.WebKit", "error", "failed"
    )
    assert system._log_entry(json.dumps({"eventType": "activityCreateEvent"})) is None
    assert system._quoted('say "hi" \\ bye') == '"say \\"hi\\" \\\\ bye"'
    refused = (({"last": "ten minutes"}, "last must be like"), ({"level": "warning"}, "level must be"), ({"limit": 0}, "limit"))
    for wrong, message in refused:
        with pytest.raises(ValueError, match=message):
            system.logs(**wrong)


@darwin
def test_logs():
    found = system.logs(last="2m", limit=5)
    assert len(found) <= 5 and all(entry.process and entry.level for entry in found)
    assert all(entry.level in ("error", "fault") for entry in system.logs(level="error", last="5m", limit=5))


def test_platform_checks():
    with pytest.raises(ValueError, match="limit"):
        system.logs(limit=-1)


def test_crash_reports_skip_corrupt_shapes_and_compare_instants(tmp_path, monkeypatch):
    from datetime import timezone

    (tmp_path / "list.ips").write_text("[1, 2]\n{}")
    header = {"app_name": "Mail", "bug_type": "309", "timestamp": "2026-09-29 13:55:00.00 -0300"}
    (tmp_path / "odd.ips").write_text(json.dumps(header) + "\n" + json.dumps({"exception": "not a dict", "termination": [1]}))
    monkeypatch.setattr(system, "_REPORT_FOLDERS", (str(tmp_path),))
    monkeypatch.setattr(system, "require_macos", lambda: None)

    found = system.crash_reports()
    assert [(crash.app, crash.reason) for crash in found] == [("Mail", None)]  # the list header skipped, nothing broken
    # 13:55 at -03:00 is 16:55 UTC: after a 15:00 UTC cutoff, before a 17:00 one.
    assert len(system.crash_reports(since=datetime(2026, 9, 29, 15, 0, tzinfo=timezone.utc))) == 1
    assert system.crash_reports(since=datetime(2026, 9, 29, 17, 0, tzinfo=timezone.utc)) == []


def test_installed_walks_every_subfolder_and_skips_odd_plists(tmp_path, monkeypatch):
    import plistlib

    deep = tmp_path / "Development" / "Tools" / "Deep.app" / "Contents"
    deep.mkdir(parents=True)
    (deep / "Info.plist").write_bytes(plistlib.dumps({"CFBundleName": "Deep", "CFBundleIdentifier": "com.example.deep"}))
    odd = tmp_path / "Odd.app" / "Contents"
    odd.mkdir(parents=True)
    (odd / "Info.plist").write_bytes(plistlib.dumps(["not", "a", "dict"]))
    monkeypatch.setattr(apps, "_APP_FOLDERS", (str(tmp_path),))
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(macos.spotlight, "search", lambda query: [])
    assert [app.name for app in apps.installed()] == ["Deep"]


def test_logs_report_log_shows_failures(monkeypatch):
    import io
    import subprocess

    class Failed:
        def __init__(self, args, **kwargs):
            # A chatty failure: far more than a pipe holds (64 KB), which must not block it.
            kwargs["stderr"].write(b"log: bad predicate\n" + b"x" * 200_000)
            self.stdout, self.returncode = io.StringIO(""), None

        def kill(self):
            raise AssertionError("it ended by itself: nothing to kill")

        def wait(self, timeout=None):
            self.returncode = 64

    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", Failed)
    with pytest.raises(macos.CommandError) as raised:
        system.logs(process="Safari")
    assert "bad predicate" in str(raised.value)


def test_logs_stop_a_log_show_that_takes_too_long(monkeypatch):
    import subprocess
    import threading

    class Endless:
        """A log show still reading: its output only ends when it's killed."""

        def __init__(self, args, **kwargs):
            self.killed, self.returncode = threading.Event(), None

        @property
        def stdout(self):
            return self

        def __iter__(self):
            self.killed.wait(5)
            return iter([])

        def close(self):
            pass

        def kill(self):
            self.killed.set()

        def wait(self, timeout=None):
            self.returncode = -9

    monkeypatch.setattr(system, "require_macos", lambda: None)
    monkeypatch.setattr(subprocess, "Popen", Endless)
    with pytest.raises(macos.CommandTimeoutError) as raised:
        system.logs(timeout=0.05)
    assert isinstance(raised.value, TimeoutError) and raised.value.cmd[:2] == ["/usr/bin/log", "show"]
    with pytest.raises(ValueError, match="timeout"):
        system.logs(timeout=0)
