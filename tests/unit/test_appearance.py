"""Unit tests for :mod:`macos.appearance`. They run on any platform."""

import contextlib

import pytest

import macos


def test_appearance_wait_for_change(monkeypatch):
    modes = iter(["light", "light", "light", "dark"])
    monkeypatch.setattr(macos.appearance, "mode", lambda: next(modes))

    assert macos.appearance.wait_for_change(interval=0.001) == "dark"


def test_set_mode(fake_run):
    macos.appearance.set_mode("light")

    assert fake_run.args[:2] == ["osascript", "-e"]
    assert fake_run.args[2].endswith("set dark mode to false")


def test_set_mode_without_the_automation_permission(fake_run):
    fake_run.returncode = 1
    fake_run.stderr = "execution error: Not authorized to send Apple events to System Events. (-1743)"

    with pytest.raises(macos.PermissionDeniedError, match="Automation"):
        macos.appearance.set_mode("dark")

    fake_run.stderr = "execution error: something else (-1)"
    with pytest.raises(macos.CommandError):
        macos.appearance.set_mode("dark")


def test_appearance_argument_checks():
    with pytest.raises(ValueError):
        macos.appearance.wait_for_change(interval=0)
    with pytest.raises(ValueError, match="'dark' or 'light'"):
        macos.appearance.set_mode("blue")


def test_accent_color_refuses_a_color_macos_did_not_convert(monkeypatch):
    from macos import appearance

    monkeypatch.setattr(appearance, "framework", lambda name: None)
    monkeypatch.setattr(appearance._objc, "cls", lambda name: 1)
    monkeypatch.setattr(appearance._objc, "autorelease_pool", contextlib.nullcontext)
    # The accent color, then the sRGB space, then nothing: the conversion failed.
    answers = iter([10, 20, None])
    monkeypatch.setattr(appearance._objc, "send", lambda *args, **kwargs: next(answers))
    with pytest.raises(macos.MacOSError, match="accent color"):
        appearance.accent_color()  # not '#000000'
