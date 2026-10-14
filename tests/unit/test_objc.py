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


@pytest.mark.skipif(sys.platform != "darwin", reason="turns a CoreFoundation run loop")
def test_a_real_ctrl_c_while_callbacks_run_comes_out_of_the_run_loop():
    import ctypes
    import os
    import signal
    import threading
    import time

    from macos import _objc, _system

    _system.framework("Foundation")
    # A callback every millisecond: a SIGINT that comes while the run loop turns is raised at the
    # entry of the next one, before any try in it, unless the run loop keeps it.
    ticked = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    probe = _objc.define_class("PymacosTestSigint", {"tick:": ("v@:@", ticked, lambda self, cmd, timer: None)})
    with _objc.autorelease_pool():
        target = _objc.send(_objc.send(probe, "alloc"), "init")
        timer = _objc.send(
            _objc.cls("NSTimer"),
            "scheduledTimerWithTimeInterval:target:selector:userInfo:repeats:",
            0.001,
            target,
            _objc.sel("tick:"),
            None,
            True,
            argtypes=(ctypes.c_double, _objc.id, ctypes.c_void_p, _objc.id, _objc.BOOL),
        )
        try:
            threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGINT)).start()
            started = time.monotonic()
            with pytest.raises(KeyboardInterrupt):
                _objc.run_until(lambda: False, 5)
            assert time.monotonic() - started < 2  # when it came, not when the wait ran out
        finally:
            _objc.send(timer, "invalidate", restype=None)
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler  # put back


@pytest.mark.skipif(sys.platform != "darwin", reason="stops a CoreFoundation run loop")
def test_a_ctrl_c_held_during_native_code_goes_to_the_scripts_own_handler():
    import signal

    from macos import _cf

    called = []

    def mine(signum, frame):  # asyncio's, a notebook's... which may not raise
        called.append((signum, frame is not None))

    previous = signal.signal(signal.SIGINT, mine)
    try:
        with _cf.deferred_interrupt():
            signal.raise_signal(signal.SIGINT)  # handled by Python here, as it would be at a callback's entry
            # Held, but the work goes on whole: this handler may not raise, and a part would pass for the result.
            assert called == [] and not _cf.interrupted()
        assert called == [(signal.SIGINT, True)]  # delivered when the block ended, with the frame it came at
        assert signal.getsignal(signal.SIGINT) is mine and not _cf.interrupted()
    finally:
        signal.signal(signal.SIGINT, previous)


@pytest.mark.skipif(sys.platform != "darwin", reason="stops a CoreFoundation run loop")
def test_a_ctrl_c_held_comes_out_even_when_the_block_fails():
    import signal

    from macos import _cf

    with pytest.raises(KeyboardInterrupt) as raised:
        with _cf.deferred_interrupt():
            signal.raise_signal(signal.SIGINT)
            assert _cf.interrupted()  # Python's own handler will raise: the work can stop
            raise ValueError("the block's own error")
    assert isinstance(raised.value.__context__, ValueError)  # the block's error stays in the traceback
    assert not _cf.interrupted()
    with _cf.deferred_interrupt():
        pass  # nothing left over to raise later, from unrelated code


@pytest.mark.skipif(sys.platform != "darwin", reason="stops a CoreFoundation run loop")
def test_a_sigint_handler_installed_during_the_block_is_kept():
    import signal

    from macos import _cf

    def theirs(signum, frame):
        pass

    previous = signal.getsignal(signal.SIGINT)
    try:
        with _cf.deferred_interrupt():
            signal.signal(signal.SIGINT, theirs)  # by a callback, or a library it calls
        assert signal.getsignal(signal.SIGINT) is theirs
    finally:
        signal.signal(signal.SIGINT, previous)


@pytest.mark.skipif(sys.platform != "darwin", reason="stops a CoreFoundation run loop")
def test_a_block_inside_another_keeps_the_ctrl_c_the_outer_one_held():
    import signal

    from macos import _cf

    seen = []  # checked outside: an assert failing inside would only become the KeyboardInterrupt's context
    with pytest.raises(KeyboardInterrupt):
        with _cf.deferred_interrupt():
            signal.raise_signal(signal.SIGINT)
            with _cf.deferred_interrupt():  # a PDF walk inside a run loop's callback, say
                seen.append(_cf.interrupted())
            seen.append(_cf.interrupted())  # still: the work after it can stop too
    assert seen == [True, True] and not _cf.interrupted()


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

    class Cancelled(BaseException):
        pass

    def cancelled(event):
        raise Cancelled

    with pytest.raises(Cancelled):
        _cf.callback(cancelled)(1)  # nor are other BaseExceptions: only a Ctrl-C or an exit
    assert not _cf.interrupted()

    import threading

    elsewhere = []

    def worker():
        try:
            _cf.callback(tap)(1)
        except KeyboardInterrupt:
            elsewhere.append("raised")

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert elsewhere == ["raised"]  # off the main thread nothing would raise it later: it goes on as before
    assert not _cf.interrupted()


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


def test_an_error_macos_gave_no_reason_for_still_reads_as_a_message():
    import ctypes

    from macos import _objc

    nothing = ctypes.c_void_p()  # the NSError out-parameter, left unset
    assert _objc.error_message(nothing) == "unknown error"
    assert _objc.error_message(nothing, "no image") == "no image"
    assert _objc.error_message(nothing, None) is None
