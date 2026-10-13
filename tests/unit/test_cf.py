"""Unit tests for :mod:`macos._cf`. They run on any platform, but the round trips through CoreFoundation itself."""

import sys

import pytest

import macos
from macos import _cf


class _FakeCF:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args):
            self.calls.append((name,) + args)
            return {"CFRunLoopGetCurrent": "loop", "CFRunLoopRunInMode": 1}.get(name)

        return call


@pytest.fixture
def fake_cf(monkeypatch):
    fake = _FakeCF()
    monkeypatch.setattr(_cf, "lib", lambda: fake)
    monkeypatch.setattr(_cf, "default_mode", lambda: "mode")
    return fake


def test_retain_leaves_null_alone(fake_cf):
    assert _cf.retain(0) == 0  # CFRetain(NULL) would abort the process
    assert _cf.retain(None) is None  # type: ignore[arg-type]
    assert fake_cf.calls == []
    assert _cf.retain(5) == 5
    assert fake_cf.calls == [("CFRetain", 5)]


def test_run_loop_source(fake_cf):
    with pytest.raises(macos.MacOSError, match="could not watch it: macOS gave no run loop source"):
        _cf.RunLoopSource(None, owned=True, what="watch it")
    assert fake_cf.calls == []

    owned = _cf.RunLoopSource(7, owned=True, what="watch it")
    owned.close()
    owned.close()  # twice is harmless
    borrowed = _cf.RunLoopSource(8, owned=False, what="watch it")
    borrowed.close()
    assert [call for call in fake_cf.calls if call[0] != "CFRunLoopGetCurrent"] == [
        ("CFRunLoopAddSource", "loop", 7, "mode"),
        ("CFRunLoopRemoveSource", "loop", 7, "mode"),
        ("CFRelease", 7),
        ("CFRunLoopAddSource", "loop", 8, "mode"),
        ("CFRunLoopRemoveSource", "loop", 8, "mode"),  # not released: its maker owns it
    ]


def test_run_loop_with_nothing_to_wait_for(fake_cf):
    assert _cf.run_loop(0.1) is False  # kCFRunLoopRunFinished
    assert fake_cf.calls == [("CFRunLoopRunInMode", "mode", 0.1, True)]


def test_spin_pauses_when_the_run_loop_has_nothing_to_wait_for(fake_cf, monkeypatch):
    import contextlib

    from macos import _objc

    slept = []
    monkeypatch.setattr(_objc, "autorelease_pool", contextlib.nullcontext)
    monkeypatch.setattr(_objc.time, "sleep", slept.append)
    _objc.spin(0.1)
    assert slept == [0.1]  # rather than spinning the CPU


@pytest.mark.skipif(sys.platform != "darwin", reason="calls CoreFoundation")
@pytest.mark.parametrize("text", ["", "plain", "a\0b é", "😀 ends with a NUL\0"])
def test_strings_come_back_whole_nul_characters_included(text):
    with _cf.owned(_cf.string(text)) as ref:
        assert _cf.to_str(ref) == text
