"""Unit tests for :mod:`macos.notifications`. They run on any platform."""

import subprocess

import pytest

import macos
from macos import _system


def test_notify_passes_text_as_arguments(fake_run):
    macos.notify('say "hi" \\ end', title="T", sound="Glass")

    args = fake_run.args
    assert args[0] == "osascript"
    assert "display notification (item 1 of argv) with title (item 2 of argv) sound name (item 3 of argv)" in args
    assert args[-3:] == ['say "hi" \\ end', "T", "Glass"]


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
    ],
)
def test_is_allowed_reads_the_notification_settings(monkeypatch, apps, expected):
    import plistlib

    monkeypatch.setattr(_system.sys, "platform", "darwin")

    def fake(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, plistlib.dumps({"apps": apps}), b"")

    monkeypatch.setattr(_system.subprocess, "run", fake)

    assert macos.notifications.is_allowed() is expected


def test_is_allowed_is_unknown_when_the_settings_are_unreadable(monkeypatch):
    monkeypatch.setattr(_system.sys, "platform", "darwin")

    def fake(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, b"not a plist", b"")

    monkeypatch.setattr(_system.subprocess, "run", fake)

    assert macos.notifications.is_allowed() is None


def test_is_allowed_gives_up_on_a_wedged_defaults(monkeypatch):
    monkeypatch.setattr(_system.sys, "platform", "darwin")

    def hung(args, **kwargs):
        assert kwargs["timeout"]
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(_system.subprocess, "run", hung)
    assert macos.notifications.is_allowed() is None
