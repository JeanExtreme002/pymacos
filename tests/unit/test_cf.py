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
@pytest.mark.parametrize(
    "text, expected",
    [("", ""), ("plain", "plain"), ("a\0b é", "a\0b é"), ("😀 \0 inside", "😀 \0 inside"), ("USB Audio\0\0\0", "USB Audio")],
)
def test_strings_come_back_whole_nul_characters_inside_included(text, expected):
    with _cf.owned(_cf.string(text)) as ref:
        assert _cf.to_str(ref) == expected  # the NULs at the end are a driver's padding


@pytest.mark.skipif(sys.platform != "darwin", reason="looks up the real runtime and libraries")
def test_a_class_or_constant_this_macos_lacks_is_not_supported_and_still_a_lookup_error():
    from macos import _objc

    with pytest.raises(macos.NotSupportedError, match="'PymacosNoSuchClass' is not loaded") as missing:
        _objc.cls("PymacosNoSuchClass")
    assert isinstance(missing.value, LookupError)  # what the callers that turn it into their own message catch
    with pytest.raises(macos.NotSupportedError, match="kPymacosNoSuchKey isn't in this version of macOS") as missing:
        _cf.constant(_cf.lib(), "kPymacosNoSuchKey")
    assert isinstance(missing.value, LookupError)
    assert _cf.constant(_cf.lib(), "kCFBooleanTrue")  # one that's there still reads


def test_to_python_raises_the_packages_error_for_what_isnt_a_property_list(fake_cf):
    # CFPropertyListCreateData answers NULL (the fake answers None to it) for a third-party driver's odd
    # property: the callers promise a MacOSError for what macOS gives them, and it stays a ValueError too.
    with pytest.raises(_cf.NotPropertyListError, match="not a property list") as caught:
        _cf.to_python(7)
    assert isinstance(caught.value, macos.MacOSError) and isinstance(caught.value, ValueError)
    assert ("CFPropertyListCreateData", None, 7, _cf._BINARY_PLIST, 0, None) in fake_cf.calls
