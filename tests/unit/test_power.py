"""Unit tests for :mod:`macos.power`. They run on any platform."""

import macos


def test_power_sleep_commands(fake_run):
    macos.power.sleep()
    assert fake_run.args == ["pmset", "sleepnow"]
    macos.power.sleep_display()
    assert fake_run.args == ["pmset", "displaysleepnow"]
    assert all(call["timeout"] for call in fake_run.calls)  # a wedged pmset mustn't hang the script


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


def test_sleep_blockers_keep_sharing_backups_and_push_services():
    from macos.power import _sleep_blockers

    kinds = ["NetworkClientActive", "BackgroundTask", "ApplePushServiceTask", "InteractivePushServiceTask"]
    entries = [{"AssertType": kind, "AssertPID": pid, "AssertLevel": 255} for pid, kind in enumerate(kinds, 1)]

    blockers = _sleep_blockers(entries)

    assert [(blocker.kind, blocker.display) for blocker in blockers] == [(kind, False) for kind in kinds]


class _FakeIOKit:
    """Power assertions, recorded instead of made."""

    SUCCESS = 0

    def __init__(self):
        self.calls = []
        self.next_id = 0

    def IOPMAssertionCreateWithName(self, kind, level, reason, out):
        self.next_id += 1
        out._obj.value = self.next_id
        self.calls.append(("create", kind, reason, self.next_id))
        return 0

    def IOPMAssertionRelease(self, assertion):
        self.calls.append(("release", assertion))


def _fake_assertions(monkeypatch):
    from macos import power

    io = _FakeIOKit()
    monkeypatch.setattr(power._iokit, "lib", lambda: io)
    monkeypatch.setattr(power._cf, "string", lambda text: text)
    monkeypatch.setattr(power._cf, "release", lambda ref: None)
    return io


def test_keep_awake_holds_while_the_block_runs(monkeypatch):
    io = _fake_assertions(monkeypatch)

    with macos.power.keep_awake(display=True, reason="job"):
        assert io.calls == [("create", "PreventUserIdleDisplaySleep", "job", 1)]
    assert io.calls[-1] == ("release", 1)


def test_keep_awake_holds_while_an_async_function_runs(monkeypatch):
    import asyncio
    import inspect

    io = _fake_assertions(monkeypatch)
    seen = []

    @macos.power.keep_awake(reason="backup")
    async def backup(value):
        await asyncio.sleep(0)
        seen.append(list(io.calls))
        return value

    assert inspect.iscoroutinefunction(backup) and backup.__name__ == "backup"
    assert io.calls == []  # making the coroutine holds nothing yet

    assert asyncio.run(backup(7)) == 7
    assert seen == [[("create", "PreventUserIdleSystemSleep", "backup", 1)]]
    assert io.calls[-1] == ("release", 1)


def test_keep_awake_decorator_holds_one_assertion_per_call(monkeypatch):
    import asyncio

    io = _fake_assertions(monkeypatch)

    @macos.power.keep_awake()
    async def job(pause):
        await asyncio.sleep(pause)

    async def both():
        await asyncio.gather(job(0.01), job(0))

    asyncio.run(both())

    created = sorted(call[3] for call in io.calls if call[0] == "create")
    released = sorted(call[1] for call in io.calls if call[0] == "release")
    assert created == released == [1, 2]  # overlapping calls release their own


def test_keep_awake_decorates_a_plain_function_and_async_with(monkeypatch):
    import asyncio

    io = _fake_assertions(monkeypatch)

    @macos.power.keep_awake()
    def work():
        return len(io.calls)

    assert work() == 1 and io.calls[-1] == ("release", 1)

    async def block():
        async with macos.power.keep_awake():
            return len(io.calls)

    assert asyncio.run(block()) == 3 and io.calls[-1] == ("release", 2)


def test_keep_awake_refuses_generator_functions(monkeypatch):
    import pytest

    _fake_assertions(monkeypatch)

    def items():
        yield 1

    async def stream():
        yield 1

    for function in (items, stream):
        with pytest.raises(TypeError, match="generator"):
            macos.power.keep_awake()(function)


def test_keep_awake_checks_the_reason(monkeypatch):
    import pytest

    io = _fake_assertions(monkeypatch)

    for reason in (None, 5):
        with pytest.raises(TypeError, match="reason"):
            macos.power.keep_awake(reason=reason)
    with pytest.raises(ValueError, match="reason"):
        macos.power.keep_awake(reason="\ud800")
    assert io.calls == []  # nothing made, so nothing to release
