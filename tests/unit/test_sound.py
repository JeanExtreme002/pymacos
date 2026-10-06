"""Unit tests for :mod:`macos.sound`. They run on any platform."""

import pytest

import macos


def test_sound_argument_checks():
    with pytest.raises(ValueError):
        macos.sound.play("Glass", volume=2)


def test_play_drains_what_it_autoreleases(monkeypatch):
    from contextlib import contextmanager

    events = []

    @contextmanager
    def pool():
        events.append("push")
        yield
        events.append("pop")

    def send(receiver, selector, *args, **kwargs):
        events.append(selector)
        return 0.0 if selector == "duration" else True

    monkeypatch.setattr(macos.sound, "_load", lambda sound: events.append("load") or 42)
    monkeypatch.setattr(macos.sound._objc, "autorelease_pool", pool)
    monkeypatch.setattr(macos.sound._objc, "send", send)
    monkeypatch.setattr(macos.sound.time, "sleep", lambda seconds: None)

    macos.sound.play("Glass")

    assert events == ["push", "load", "setVolume:", "duration", "play", "pop", "release"]  # released after
