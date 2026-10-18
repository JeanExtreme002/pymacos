"""Unit tests for :mod:`macos.notifications`. They run on any platform."""


import os
import subprocess

import pytest

import macos
from macos import _system


@pytest.fixture(autouse=True)
def sounds(monkeypatch):
    """The alert sounds installed, the same on any host."""
    monkeypatch.setattr(macos.sound, "names", lambda: ["Basso", "Glass", "Ping"])


def test_notify_passes_text_as_arguments(fake_run):
    macos.notify('say "hi" \\ end', title="T", sound="Glass")

    args = fake_run.args
    assert args[0] == "osascript"
    assert "display notification (item 1 of argv) with title (item 2 of argv) sound name (item 3 of argv)" in args
    assert args[-3:] == ['say "hi" \\ end', "T", "Glass"]
    assert fake_run.calls[-1]["timeout"]  # an osascript that never ends doesn't hang the caller


def test_notify_message_only(fake_run):
    macos.notify("hello")

    assert "display notification (item 1 of argv)" in fake_run.args
    assert fake_run.args[-1] == "hello"


def test_notify_ends_options_before_user_text(fake_run):
    macos.notify("-5 degrees", title="-e")

    args = fake_run.args
    assert args[-3:] == ["--", "-5 degrees", "-e"]


def test_notify_spells_the_sound_as_macos_does(fake_run):
    macos.notify("x", sound="glass")
    assert fake_run.args[-1] == "Glass"


@pytest.mark.parametrize("sound", ["Glas", "Glass.aiff", "Basso "])
def test_notify_rejects_an_unknown_sound(fake_run, sound):
    # macOS would post the notification without a sound, and no error.
    with pytest.raises(ValueError, match="macos.sound.names"):
        macos.notify("x", sound=sound)
    assert fake_run.calls == []


def test_notify_passes_any_sound_when_none_can_be_listed(fake_run, monkeypatch):
    monkeypatch.setattr(macos.sound, "names", lambda: [])
    macos.notify("x", sound="Custom")
    assert fake_run.args[-1] == "Custom"


@pytest.mark.parametrize(
    "kwargs, name",
    [
        ({"message": "a\0b"}, "message"),
        ({"message": "x", "title": "\ud800"}, "title"),
        ({"message": "x", "subtitle": "a\0"}, "subtitle"),
        ({"message": "x", "sound": "Gla\0ss"}, "sound"),
    ],
)
def test_notify_rejects_text_that_cant_be_an_argument(fake_run, kwargs, name):
    with pytest.raises(ValueError, match="notify\\(\\): {} contains".format(name)):
        macos.notify(**kwargs)
    assert fake_run.calls == []


def test_notify_keeps_a_file_names_surrogate_escapes(fake_run):
    text = os.fsdecode(b"\xff.txt")  # a file name that isn't UTF-8: it still travels as its bytes
    macos.notify(text)
    assert fake_run.args[-1] == text


def test_notify_clips_long_text(fake_run):
    macos.notify("x" * 3_000_000, title="t" * 5000)

    message, title = fake_run.args[-2:]
    assert len(message) == len(title) == 4096
    assert message.endswith("x\u2026") and title.endswith("t\u2026")


def test_notify_refuses_when_notifications_are_off(fake_run, monkeypatch):
    monkeypatch.setattr(macos.notifications, "is_allowed", lambda: False)

    with pytest.raises(macos.PermissionDeniedError, match="Script Editor"):
        macos.notify("x")
    assert fake_run.calls == []


def test_notify_checks_again_after_the_first_notification(fake_run, monkeypatch):
    answers = iter([None, False])  # unknown before posting, blocked right after
    monkeypatch.setattr(macos.notifications, "is_allowed", lambda: next(answers))

    with pytest.raises(macos.PermissionDeniedError):
        macos.notify("x")
    assert fake_run.args[0] == "osascript"


def test_notify_can_skip_the_check(fake_run, monkeypatch):
    monkeypatch.setattr(macos.notifications, "is_allowed", lambda: False)

    macos.notify("x", check_permission=False)
    assert fake_run.args[0] == "osascript"


@pytest.mark.parametrize(
    "apps, expected",
    [
        ([{"bundle-id": "com.apple.ScriptEditor2", "flags": 41951246}], True),
        ([{"bundle-id": "com.apple.ScriptEditor2", "flags": 8206}], False),
        ([{"bundle-id": "com.other.app", "flags": 41951246}], None),
        ([], None),
        ("not a list", None),
        ([{"bundle-id": "com.apple.ScriptEditor2", "flags": "many"}], None),
        # Missing, or not an integer: unknown, never "turned off", which would block notify().
        ([{"bundle-id": "com.apple.ScriptEditor2"}], None),
        ([{"bundle-id": "com.apple.ScriptEditor2", "flags": True}], None),
        ([{"bundle-id": "com.apple.ScriptEditor2", "flags": float("inf")}], None),
        ([{"bundle-id": "com.apple.ScriptEditor2", "flags": 3.5}], None),
    ],
)
def test_is_allowed_reads_the_notification_settings(monkeypatch, apps, expected):
    monkeypatch.setattr(_system.sys, "platform", "darwin")
    asked = []

    def read(domain, key=None, **kwargs):
        asked.append((domain, key))
        return apps

    monkeypatch.setattr(macos.defaults, "read", read)
    monkeypatch.setattr(macos.defaults, "_synchronize", lambda domain: asked.append(("synchronize", domain)))
    # In this process, through CFPreferences: no ``defaults export`` started for every notification.
    monkeypatch.setattr(_system.subprocess, "run", lambda *args, **kwargs: pytest.fail("a command was run"))

    assert macos.notifications.is_allowed() is expected
    # Synchronized first: what System Settings wrote since, not this process's copy.
    assert asked == [("synchronize", "com.apple.ncprefs"), ("com.apple.ncprefs", "apps")]


@pytest.mark.parametrize("failure", [macos.MacOSError("cfprefsd didn't answer"), ValueError("not a property list"), OSError()])
def test_is_allowed_is_unknown_when_the_settings_cant_be_read(monkeypatch, failure):
    monkeypatch.setattr(_system.sys, "platform", "darwin")

    def read(domain, key=None, **kwargs):
        raise failure

    monkeypatch.setattr(macos.defaults, "read", read)
    monkeypatch.setattr(macos.defaults, "_synchronize", lambda domain: None)
    assert macos.notifications.is_allowed() is None
    # The synchronizing can fail the same way: still unknown, never an error out of notify().
    monkeypatch.setattr(macos.defaults, "_synchronize", read)
    assert macos.notifications.is_allowed() is None


def test_is_allowed_needs_macos(monkeypatch):
    monkeypatch.setattr(_system.sys, "platform", "linux")
    with pytest.raises(macos.NotSupportedError):
        macos.notifications.is_allowed()


def test_notify_posts_when_the_switch_is_missing(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(_system.sys, "platform", "darwin")
    monkeypatch.setattr(_system.subprocess, "run", run)
    monkeypatch.setattr(macos.defaults, "_synchronize", lambda domain: None)
    monkeypatch.setattr(macos.defaults, "read", lambda domain, key=None, **kwargs: [{"bundle-id": "com.apple.ScriptEditor2"}])

    macos.notify("x")
    assert len(calls) == 1 and calls[0][0].endswith("osascript")
