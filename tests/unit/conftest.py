"""Fixtures shared by the unit tests: fake system commands and events."""

import subprocess
from typing import List

import pytest

import macos
from macos import _system, notifications


class FakeRun:
    """Records the commands passed to ``subprocess.run`` instead of running them."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = "") -> None:
        self.calls: List[dict] = []
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr

    def __call__(self, args, **kwargs):
        self.calls.append({"args": list(args), **kwargs})
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)

    @property
    def args(self) -> List[str]:
        return self.calls[-1]["args"]


@pytest.fixture
def fake_run(monkeypatch):
    """Pretend to be on macOS and capture system commands."""
    fake = FakeRun()
    monkeypatch.setattr(_system.sys, "platform", "darwin")
    monkeypatch.setattr(_system.subprocess, "run", fake)
    # notify() reads the notification settings first; in unit tests they allow it.
    monkeypatch.setattr(notifications, "is_allowed", lambda: True)
    return fake


class _Commands:
    """A fake ``subprocess.run`` that answers each command from a table."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, args, **kwargs):
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["shortcuts", "run"]:
            for flag, path in zip(args, args[1:]):
                if flag == "--input-path" and path.endswith(".txt"):
                    self.text_input = open(path, encoding="utf-8").read()
        key = " ".join(args[:3]) if args[:2] == ["shortcuts", "list"] else args[1]
        returncode, stdout, stderr = self.answers.get(key, (0, "", ""))
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)


@pytest.fixture
def commands(fake_run, monkeypatch):
    fake = _Commands({})
    monkeypatch.setattr(_system.subprocess, "run", fake)
    return fake


class _FakeEvents:
    """Stands in for Core Graphics: records the events built and posted, in order."""

    def __init__(self):
        self.events = {}
        self.posted = []
        self.pointer = (10.0, 20.0)

    def _new(self, **fields):
        number = len(self.events) + 1
        self.events[number] = fields
        return number

    def CGEventCreateKeyboardEvent(self, source, code, down):
        return self._new(kind="key", code=code, down=down, flags=0, text=None)

    def CGEventSetFlags(self, event, flags):
        self.events[event]["flags"] = flags

    def CGEventKeyboardSetUnicodeString(self, event, length, units):
        self.events[event]["text"] = bytes(units)[: length * 2].decode("utf-16-le")

    def CGEventCreateMouseEvent(self, source, kind, point, button):
        return self._new(kind=kind, x=point.x, y=point.y, button=button, clicks=0, flags=0)

    def CGEventSetIntegerValueField(self, event, field, value):
        self.events[event]["clicks"] = value

    def CGEventCreateScrollWheelEvent2(self, source, units, count, vertical, sideways, third):
        return self._new(kind="scroll", vertical=vertical, sideways=sideways)

    def CGEventCreate(self, source):
        return self._new(kind="probe")

    def CGEventGetLocation(self, event):
        from macos._objc import CGPoint

        return CGPoint(*self.pointer)

    released = ()  # the fake events are numbers, not CF objects: releasing them is a no-op (see fake_events)

    flags_state = 0

    def CGEventSourceFlagsState(self, state):
        return self.flags_state


@pytest.fixture
def fake_events(monkeypatch):
    from macos import _events

    fake = _FakeEvents()
    monkeypatch.setattr(_events, "graphics", lambda: fake)
    monkeypatch.setattr(_events, "has_permission", lambda: True)
    monkeypatch.setattr(_events, "post", lambda event: fake.posted.append(fake.events[event]))
    monkeypatch.setattr(_events._cf, "release", lambda ref: None)  # the events are fake numbers, not CF objects
    monkeypatch.setattr(macos.keyboard, "_layout", lambda: {"c": (8, False), "?": (44, True), "+": (24, True)})
    return fake
