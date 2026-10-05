"""Unit tests for :mod:`macos.power`. They run on any platform."""

import macos


def test_power_sleep_commands(fake_run):
    macos.power.sleep()
    assert fake_run.args == ["pmset", "sleepnow"]
    macos.power.sleep_display()
    assert fake_run.args == ["pmset", "displaysleepnow"]


def test_battery_health_fields_are_optional():
    battery = macos.power.Battery(percent=50, charging=False, plugged_in=False, time_remaining=None)

    assert battery.cycle_count is None and battery.health is None


def test_sleep_blockers_keep_the_ones_that_block_sleep():
    from datetime import datetime, timedelta, timezone

    from macos.power import _sleep_blockers

    started = datetime(2026, 9, 30, 19, 0, 0)
    entries = [
        {"AssertType": "UserIsActive", "AssertPID": 411, "Process Name": "WindowServer", "AssertStartWhen": started},
        {
            "AssertType": "NoDisplaySleepAssertion",
            "AssertPID": 990,
            "Process Name": "Google Chrome",
            "AssertName": "Video Wake Lock",
            "AssertStartWhen": started + timedelta(minutes=5),
            "AssertLevel": 255,
        },
        {
            "AssertType": "PreventUserIdleSystemSleep",
            "AssertPID": 1234,
            "Process Name": "caffeinate",
            "AssertName": "caffeinate command-line tool",
            "AssertStartWhen": started,
            "TimeoutSeconds": 300.0,
            "AssertLevel": 255,
        },
        {"AssertType": "PreventUserIdleSystemSleep", "AssertPID": 7, "AssertLevel": 0},  # released
        {"AssertType": "ExternalMedia", "AssertPID": 8, "AssertStartWhen": started},  # only delays standby
        "not an assertion",
    ]

    blockers = _sleep_blockers(entries)

    assert [(blocker.process, blocker.display) for blocker in blockers] == [("caffeinate", False), ("Google Chrome", True)]
    caffeinate = blockers[0]
    local = started.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
    assert caffeinate.since == local and caffeinate.until == local + timedelta(seconds=300)
    assert blockers[1].until is None and blockers[1].reason == "Video Wake Lock" and blockers[1].pid == 990


def test_iokit_is_declared_once_for_every_module():
    import sys

    import pytest

    if sys.platform != "darwin":
        pytest.skip("loads IOKit")
    from macos import _cf, _iokit, _system

    io = _iokit.lib()
    assert io is _iokit.lib() is _system.framework("IOKit")  # one handle, its signatures set once
    for name in ("IOPSCopyPowerSourcesInfo", "IOPSCopyExternalPowerAdapterDetails", "IORegistryEntryCreateCFProperty"):
        assert getattr(io, name).restype is _cf.CFTypeRef
    assert macos.power.battery() is None or 0 <= macos.power.battery().percent <= 100
