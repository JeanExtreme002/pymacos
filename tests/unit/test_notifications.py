"""Unit tests for :mod:`macos.notifications`. They run on any platform."""


import pytest

import macos
from macos import _system


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
