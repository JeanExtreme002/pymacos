"""Unit tests for :mod:`macos._cf`. They run on any platform, but the round trips through CoreFoundation itself."""

import ctypes
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
        ("CFRetain", "loop"),  # the thread's run loop is freed when the thread ends: close() may come after
        ("CFRunLoopAddSource", "loop", 7, "mode"),
        ("CFRunLoopRemoveSource", "loop", 7, "mode"),
        ("CFRelease", 7),
        ("CFRelease", "loop"),
        ("CFRetain", "loop"),
        ("CFRunLoopAddSource", "loop", 8, "mode"),
        ("CFRunLoopRemoveSource", "loop", 8, "mode"),  # not released: its maker owns it
        ("CFRelease", "loop"),
    ]


def test_run_loop_source_closes_from_another_thread_after_its_own_ended(fake_cf):
    import threading

    made = []
    worker = threading.Thread(target=lambda: made.append(_cf.RunLoopSource(7, owned=True, what="watch it")))
    worker.start()
    worker.join()
    made[0].close()  # on the main thread, the worker gone: the loop it retained is still there
    assert fake_cf.calls[-3:] == [
        ("CFRunLoopRemoveSource", "loop", 7, "mode"),
        ("CFRelease", 7),
        ("CFRelease", "loop"),
    ]
    assert made[0].loop is None


def test_from_python_rejects_none_at_any_depth(fake_cf):
    for value in (None, [1, None], {"a": None}, {"a": [{"b": None}]}, (None,)):
        with pytest.raises(ValueError, match="None is not a property-list value"):
            _cf.from_python(value)
    assert fake_cf.calls == []  # nothing reached CoreFoundation


def test_from_python_takes_aware_datetimes_as_utc(fake_cf):
    import datetime
    import plistlib

    created = []
    fake_cf.CFDataCreate = lambda allocator, payload, size: created.append(payload) or 3
    fake_cf.CFPropertyListCreateWithData = lambda *args: 9
    naive = datetime.datetime(2026, 10, 17, 15, 0)
    aware = datetime.datetime(2026, 10, 17, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
    assert _cf.from_python({"when": aware, "list": [aware, naive], "tuple": (aware,)}) == 9
    assert plistlib.loads(created[0]) == {"when": naive, "list": [naive, naive], "tuple": [naive]}


def test_to_python_raises_the_packages_error_for_what_plistlib_cannot_read(fake_cf, monkeypatch):
    fake_cf.CFPropertyListCreateData = lambda *args: 3
    monkeypatch.setattr(_cf, "to_bytes", lambda ref: b"bplist00 not really")
    with pytest.raises(_cf.NotPropertyListError, match="not a property list Python can read") as caught:
        _cf.to_python(7)
    assert isinstance(caught.value, ValueError)


def test_to_str_replaces_a_lone_surrogate_and_keeps_the_rest(fake_cf, monkeypatch):
    units = "a\ud83dbc\0".encode("utf-16-le", "surrogatepass")
    monkeypatch.setattr(_cf, "is_type", lambda ref, type_id: True)
    fake_cf.CFStringGetLength = lambda ref: len(units) // 2

    def characters(ref, span, buffer):
        assert (span.location, span.length) == (0, len(units) // 2)
        ctypes.memmove(buffer, units, len(units))

    fake_cf.CFStringGetCharacters = characters
    assert _cf.to_str(7) == "a\ufffdbc"


@pytest.mark.skipif(sys.platform != "darwin", reason="calls CoreFoundation")
def test_a_lone_surrogate_in_a_real_cfstring():
    units = "a\ud83dbc".encode("utf-16-le", "surrogatepass")
    with _cf.owned(_cf.lib().CFStringCreateWithBytes(None, units, len(units), 0x14000100, False)) as ref:  # UTF-16LE
        assert _cf.to_str(ref) == "a\ufffdbc"  # not None for the whole string
        with pytest.raises(_cf.NotPropertyListError):
            _cf.to_python(ref)


@pytest.mark.skipif(sys.platform != "darwin", reason="calls CoreFoundation")
def test_dates_round_trip_as_naive_utc():
    import datetime

    aware = datetime.datetime(2026, 10, 17, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
    with _cf.owned(_cf.from_python([aware])) as ref:
        assert _cf.to_python(ref) == [datetime.datetime(2026, 10, 17, 15, 0)]


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
