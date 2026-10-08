"""Unit tests for the Objective-C bridge: blocks and runtime classes."""

import sys

import pytest


@pytest.mark.skipif(sys.platform != "darwin", reason="calls the Objective-C runtime")
def test_objc_blocks_and_classes():
    import ctypes

    from macos import _objc

    seen = []
    with _objc.autorelease_pool():
        items = _objc.nsarray_of([_objc.nsstring(text) for text in ("a", "b")])
        each = _objc.block(
            lambda item, index, stop: seen.append((_objc.pystring(item), index)),
            b"v@?@Q^c",
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
        )
        _objc.send(items, "enumerateObjectsUsingBlock:", each, argtypes=(ctypes.c_void_p,), restype=None)
    assert seen == [("a", 0), ("b", 1)]

    echo = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    made = _objc.define_class("PymacosTestEcho", {"echo:": ("@@:@", echo, lambda self, cmd, value: value)})
    assert _objc.define_class("PymacosTestEcho", {}) == made  # made once
    with _objc.autorelease_pool():
        answer = _objc.send(_objc.new("PymacosTestEcho"), "echo:", _objc.nsstring("hi"), argtypes=(_objc.id,))
        assert _objc.pystring(answer) == "hi"

    assert _objc.run_until(lambda: True, 1) is True
    assert _objc.run_until(lambda: False, 0.1) is False


def test_one_cicontext_is_made_even_for_first_renders_at_once(monkeypatch):
    import threading
    import time

    from macos import _objc

    made = []

    def send(receiver, selector, *args, **kwargs):
        if selector == "contextWithOptions:":
            time.sleep(0.05)  # long enough for the other thread to ask meanwhile
            made.append(len(made) + 1)
            return made[-1]
        return receiver  # retain

    monkeypatch.setattr(_objc, "_CICONTEXT", [])
    monkeypatch.setattr(_objc, "send", send)
    monkeypatch.setattr(_objc, "cls", lambda name: 0)
    got = []
    threads = [threading.Thread(target=lambda: got.append(_objc.cicontext())) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert made == [1] and got == [1, 1, 1, 1]  # one context, none made only to leak
