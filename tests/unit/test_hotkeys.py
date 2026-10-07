"""Unit tests for :mod:`macos.hotkeys` and the event tap it shares with :mod:`macos.keyboard`. They run on any platform."""

import threading

import pytest

import macos
from macos import _events, hotkeys

CMD, OPTION, CONTROL, FN = 1 << 20, 1 << 19, 1 << 18, 1 << 23
KEY_DOWN, KEY_UP = 10, 11


def test_hotkeys_registry():
    assert hotkeys._combination("ctrl+option+cmd+f19") == (80, CONTROL | OPTION | CMD)
    assert hotkeys._combination("f5") == (96, 0)  # no Fn: macOS adds it to F5 by itself, see _match
    assert hotkeys._combination("fn+f5") == (96, FN)

    first = hotkeys.register("ctrl+f19", lambda: "first")
    second = hotkeys.register("ctrl+f19", lambda: "second")  # replaces it
    try:
        assert hotkeys._registered[(80, CONTROL)] is second
        first.unregister()  # the same keys: removes the current one
        assert (80, CONTROL) not in hotkeys._registered
    finally:
        hotkeys.unregister("ctrl+f19")


def test_hotkeys_argument_checks():
    with pytest.raises(ValueError, match="not a modifier"):
        hotkeys.register("hyper+k", lambda: None)


@pytest.fixture
def registered(monkeypatch):
    # A US keyboard's letters, without asking macOS.
    monkeypatch.setattr(macos.keyboard, "_layout", lambda: {"k": (40, False), "j": (38, False), "o": (31, False)})
    made = []

    def register(keys):
        made.append(hotkeys.register(keys, lambda: None))
        return made[-1]._combination

    yield register
    for hotkey in made:
        hotkey.unregister()


def test_function_keys_and_arrows_match_with_the_fn_flag_macos_adds(registered):
    f5, left, k = registered("f5"), registered("cmd+left"), registered("cmd+k")
    caps_lock = 1 << 16

    assert hotkeys._match(96, FN) == f5  # F5 as macOS reports it: with Fn, unpressed
    assert hotkeys._match(96, FN | caps_lock) == f5
    assert hotkeys._match(123, CMD | FN) == left
    assert hotkeys._match(40, CMD | FN) is None  # a letter with Fn really held is another shortcut
    assert hotkeys._match(40, CMD) == k
    fn_f5 = registered("fn+f5")
    assert hotkeys._match(96, FN) == fn_f5  # asked for explicitly: it wins


class _FakeGraphics:
    """Core Graphics for an event tap: keeps the tap's callback, and answers for fake key events."""

    def __init__(self):
        self.events = {}
        self.callback = None
        self.enabled = []

    def key(self, code, flags, repeat=False):
        number = len(self.events) + 1
        self.events[number] = (code, flags, repeat)
        return number

    def CGEventTapCreate(self, tap, place, options, mask, callback, info):
        self.callback = callback
        return 4242

    def CGEventTapEnable(self, port, on):
        self.enabled.append(on)

    def CGEventGetIntegerValueField(self, event, field):
        code, _, repeat = self.events[event]
        return {9: code, 8: int(repeat)}[field]

    def CGEventGetFlags(self, event):
        return self.events[event][1]


@pytest.fixture
def fake_tap(monkeypatch):
    fake = _FakeGraphics()
    closed = []

    class Source:
        def __init__(self, source, *, owned, what):
            pass

        def close(self):
            closed.append(True)

    monkeypatch.setattr(_events, "graphics", lambda: fake)
    monkeypatch.setattr(_events._cf, "RunLoopSource", Source)

    class CoreFoundation:
        def CFMachPortCreateRunLoopSource(self, allocator, port, order):
            return 1

        def CFMachPortInvalidate(self, port):
            closed.append("port")

    monkeypatch.setattr(_events._cf, "lib", CoreFoundation)
    monkeypatch.setattr(_events._cf, "release", lambda ref: None)
    fake.closed = closed
    return fake


def _tap(listener):
    return _events.Tap([KEY_DOWN, KEY_UP], hotkeys._handler(listener), listener, listen_only=False, denied="no")


def test_the_tap_swallows_f5_carrying_the_fn_flag(fake_tap, registered):
    f5 = registered("f5")
    listener = hotkeys._Listener(None)
    with hotkeys._listeners.listening(listener):
        _tap(listener)
        down, up = fake_tap.key(96, FN), fake_tap.key(96, FN)
        assert fake_tap.callback(0, KEY_DOWN, down, 0) is None  # kept from the app in front
        assert fake_tap.callback(0, KEY_UP, up, 0) is None  # and its key up too
        other = fake_tap.key(97, FN)  # F6: not registered
        assert fake_tap.callback(0, KEY_DOWN, other, 0) == other
        repeat = fake_tap.key(96, FN, repeat=True)
        assert fake_tap.callback(0, KEY_DOWN, repeat, 0) is None
    assert list(listener.pending) == [f5]  # once, though held

    assert fake_tap.callback(0, 0xFFFFFFFE, 77, 0) == 77  # switched off by macOS: on again
    assert fake_tap.enabled == [True]


def test_an_error_in_the_tap_lets_the_key_through_and_comes_out_of_the_listener(fake_tap, monkeypatch):
    listener = _events.Listener()

    def broken(kind, event):
        raise KeyError("bug")

    _events.Tap([KEY_DOWN], broken, listener, listen_only=False, denied="no")
    event = fake_tap.key(1, 0)
    assert fake_tap.callback(0, KEY_DOWN, event, 0) == event  # not swallowed, nothing crosses into C
    monkeypatch.setattr(_events._objc, "spin", lambda seconds: None)
    with pytest.raises(KeyError, match="bug"):
        list(listener.drain(1))


def test_listen_raises_what_convert_raised(fake_tap, monkeypatch):
    monkeypatch.setattr(_events._objc, "spin", lambda seconds: fake_tap.callback(0, KEY_DOWN, fake_tap.key(1, 0), 0))

    def convert(kind, event):
        raise ZeroDivisionError("in convert")

    with pytest.raises(ZeroDivisionError, match="in convert"):
        next(_events.listen([KEY_DOWN], convert, 1, "no"))
    assert fake_tap.closed == [True, "port"]  # the tap is taken off the run loop, and its port closed


def test_a_shortcut_goes_to_every_wait_for_it_and_to_one_run(registered):
    k, j = registered("cmd+k"), registered("cmd+j")
    first_run, second_run = hotkeys._Listener(None), hotkeys._Listener(None)
    waiting_k, waiting_j = hotkeys._Listener(k), hotkeys._Listener(j)
    with hotkeys._listeners.listening(waiting_k), hotkeys._listeners.listening(waiting_j):
        hotkeys._dispatch(j, waiting_k)  # no run(): the wait() that caught it serves cmd+j's waiter only
        assert list(waiting_j.pending) == [j] and not waiting_k.pending
        hotkeys._dispatch(k, waiting_j)
        assert list(waiting_k.pending) == [k]
        waiting_k.pending.clear(), waiting_j.pending.clear()
        with hotkeys._listeners.listening(first_run), hotkeys._listeners.listening(second_run):
            hotkeys._dispatch(k, second_run)
            assert list(waiting_k.pending) == [k] and list(first_run.pending) == [k] and not second_run.pending
    other = registered("cmd+o")
    hotkeys._dispatch(other, waiting_j)  # nobody else listens: the one that caught it calls it
    assert list(waiting_j.pending) == [other]


def test_stop_reaches_every_listener_and_is_kept_from_the_start(monkeypatch):
    started = threading.Event()

    def tap(*args, **kwargs):
        started.set()
        hotkeys.stop()  # while the tap is being set up
        return type("Tap", (), {"close": lambda self: None})()

    monkeypatch.setattr(_events, "Tap", tap)
    monkeypatch.setattr(_events, "graphics", lambda: None)
    monkeypatch.setattr(_events._objc, "spin", lambda seconds: pytest.fail("stop() was lost"))
    hotkeys.run(timeout=5)
    assert started.is_set()

    listeners = [hotkeys._Listener(None), hotkeys._Listener((1, 0))]
    with hotkeys._listeners.listening(listeners[0]), hotkeys._listeners.listening(listeners[1]):
        macos.hotkeys.stop()
    assert all(listener.stop.is_set() for listener in listeners)
    assert hotkeys._listeners.active() == []


def test_the_tap_keeps_handling_keys_while_a_callback_runs(fake_tap, registered, monkeypatch):
    # The tap turns its own thread's run loop: a slow callback must not hold up the keys typed meanwhile.
    k = registered("cmd+k")
    caller = threading.current_thread()
    in_callback, let_go = threading.Event(), threading.Event()
    answers, tap_threads = [], []

    def spin(seconds):
        tap_threads.append(threading.current_thread())
        if not answers:
            answers.append(fake_tap.callback(0, KEY_DOWN, fake_tap.key(40, CMD), 0))  # the shortcut
        elif in_callback.is_set() and len(answers) == 1:
            other = fake_tap.key(38, 0)  # "j", typed while the callback still runs
            answers.append(fake_tap.callback(0, KEY_DOWN, other, 0) == other)
            let_go.set()
        threading.Event().wait(0.001)

    monkeypatch.setattr(_events._objc, "spin", spin)
    called = []

    def callback():
        called.append(threading.current_thread())
        in_callback.set()
        assert let_go.wait(5), "the tap stalled while the callback ran"
        hotkeys.stop()

    hotkeys.register("cmd+k", callback)
    hotkeys.run(timeout=5)

    assert answers == [None, True]  # the shortcut kept from the app, then "j" passed straight through
    assert called == [caller]  # callbacks on the caller's thread
    assert tap_threads and caller not in tap_threads  # the tap on another
    assert k in hotkeys._registered


def test_a_tap_macos_refuses_raises_on_the_callers_thread(monkeypatch):
    def refuse(*args, **kwargs):
        raise macos.PermissionDeniedError("no tap")

    monkeypatch.setattr(_events, "Tap", refuse)
    monkeypatch.setattr(_events, "graphics", lambda: None)
    with pytest.raises(macos.PermissionDeniedError, match="no tap"):
        hotkeys.run(timeout=1)
    assert hotkeys._listeners.active() == []


def test_ctrl_c_while_the_tap_starts_stops_the_tap_too(monkeypatch):
    import threading
    from types import SimpleNamespace

    closed = []

    class Tap:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            closed.append(True)

    class Interrupted(threading.Event):
        def wait(self, timeout=None):
            if timeout is None:  # the wait for the tap to start: Ctrl-C lands there
                raise KeyboardInterrupt
            return super().wait(timeout)

    monkeypatch.setattr(_events, "Tap", Tap)
    monkeypatch.setattr(_events, "graphics", lambda: None)
    monkeypatch.setattr(hotkeys, "threading", SimpleNamespace(**{**vars(threading), "Event": Interrupted}))
    monkeypatch.setattr(hotkeys._objc, "spin", lambda seconds: None)
    with pytest.raises(KeyboardInterrupt):
        hotkeys.run(timeout=1)
    assert closed == [True]  # no tap left behind, swallowing the shortcuts
    assert hotkeys._listeners.active() == []
