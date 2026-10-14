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


@pytest.mark.parametrize(
    "machine, restype, stret",
    [
        ("x86_64", "CGRect", True),  # 32 bytes: returned through a hidden pointer on Intel
        ("x86_64", "CGPoint", False),  # 16 bytes: in registers
        ("x86_64", "c_double", False),
        ("arm64", "CGRect", False),  # arm64 has no _stret variant
    ],
)
def test_struct_returns_pick_the_stret_trampoline_only_on_intel(monkeypatch, machine, restype, stret):
    import ctypes

    from macos import _objc

    resolved = getattr(_objc, restype, None) or getattr(ctypes, restype)
    monkeypatch.setattr(_objc.platform, "machine", lambda: machine)
    assert _objc._needs_stret(resolved) is stret

    # The prototype is cached by return type: call the function under the cache, with a stand-in runtime.
    class Runtime:
        objc_msgSend = ctypes.c_void_p(0x1000)
        objc_msgSend_stret = ctypes.c_void_p(0x2000)

    monkeypatch.setattr(_objc, "_libobjc", lambda: Runtime)
    prototype = _objc._prototype.__wrapped__(resolved, ())
    assert ctypes.cast(prototype, ctypes.c_void_p).value == (0x2000 if stret else 0x1000)


@pytest.mark.skipif(sys.platform != "darwin", reason="turns a CoreFoundation run loop")
def test_a_ctrl_c_inside_a_callback_comes_out_of_the_run_loop():
    import ctypes
    import time

    from macos import _objc, _system

    _system.framework("Foundation")

    def fire(self, cmd, timer):
        raise KeyboardInterrupt  # Ctrl-C, landing while the callback runs: ctypes alone would print it and go on

    fired = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    probe = _objc.define_class("PymacosTestCtrlC", {"fire:": ("v@:@", fired, fire)})
    with _objc.autorelease_pool():
        target = _objc.send(_objc.send(probe, "alloc"), "init")
        _objc.send(
            _objc.cls("NSTimer"),
            "scheduledTimerWithTimeInterval:target:selector:userInfo:repeats:",
            0.05,
            target,
            _objc.sel("fire:"),
            None,
            False,
            argtypes=(ctypes.c_double, _objc.id, ctypes.c_void_p, _objc.id, _objc.BOOL),
        )
        started = time.monotonic()
        with pytest.raises(KeyboardInterrupt):
            _objc.run_until(lambda: False, 5)
    assert time.monotonic() - started < 2  # at once, not when the wait ran out
    _objc.run_until(lambda: False, 0.05)  # raised once


@pytest.mark.skipif(sys.platform != "darwin", reason="stops a CoreFoundation run loop")
def test_a_callback_interrupted_hands_back_its_fallback():
    import ctypes

    from macos import _cf

    def tap(event):
        raise KeyboardInterrupt

    def broken(event):
        raise ValueError("its own error")

    called_from_c = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(_cf.callback(tap, lambda event: event))
    assert called_from_c(1234) == 1234  # an event tap's event goes on
    with pytest.raises(KeyboardInterrupt):
        _cf.raise_interrupt()
    with pytest.raises(ValueError, match="its own error"):
        _cf.callback(broken)(1)  # other exceptions go on as before
    _cf.raise_interrupt()  # and aren't kept


@pytest.mark.skipif(sys.platform != "darwin", reason="calls the Objective-C runtime")
def test_classes_made_before_a_reload_keep_working():
    import subprocess
    import textwrap

    # In a process of its own: reloading _objc here would swap it under the other tests.
    code = textwrap.dedent(
        """
        import ctypes, gc, importlib
        from macos import _objc

        echo = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
        made = _objc.define_class("PymacosTestReload", {"echo:": ("@@:@", echo, lambda self, cmd, value: value)})
        with _objc.autorelease_pool():
            probe = _objc.send(_objc.send(made, "alloc"), "init")
        importlib.reload(_objc)  # what autoreload does in a notebook
        gc.collect()
        reused = [ctypes.CFUNCTYPE(None)(lambda: None) for _ in range(2000)]  # takes any memory freed
        assert _objc.define_class("PymacosTestReload", {}) == made
        with _objc.autorelease_pool():
            print(_objc.send(probe, "echo:", 1234, argtypes=(ctypes.c_void_p,)))
        """
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "1234"  # the method still calls its own callback, not freed memory
