"""Unit tests for :mod:`macos.events`. They run on any platform."""

import pytest

import macos
from macos import events


@pytest.fixture(autouse=True)
def no_handlers():
    events._handlers.clear()
    yield
    events._handlers.clear()


def test_events_registry():
    first = events.on("wake", print)
    second = events.on("wake", repr)
    launched = events.on("app_launched", print)

    assert repr(first) == "Handler('wake')"
    first.remove()
    assert events._handlers == [second, launched]
    events.off("wake")
    assert events._handlers == [launched]
    events.off(launched)
    events.off(launched)  # removing twice is harmless
    assert events._handlers == []


def test_events_argument_checks():
    with pytest.raises(ValueError, match="unknown event 'coffee'"):
        events.on("coffee", print)
    with pytest.raises(ValueError, match="unknown event"):
        events.wait("coffee")
    with pytest.raises(ValueError, match="unknown event"):
        events.off("coffee")
    with pytest.raises(ValueError, match="no callbacks registered"):
        events.run()


def test_events_run_calls_the_callbacks_of_each_event(monkeypatch):
    calls = []
    events.on("wake", lambda event: calls.append(("a", event.name)))
    events.on("wake", lambda event: calls.append(("b", event.name)))
    events.on("sleep", lambda event: calls.append(("c", event.name)))
    events.on("sleep", lambda: calls.append(("d", "no arguments")))
    events.on("sleep", print)  # a builtin: it gets the event

    def listen(names, on_event, timeout):
        assert names == ["sleep", "wake"]
        for name in ("wake", "sleep"):
            on_event(macos.events.Event(name))

    monkeypatch.setattr(events, "_listen", listen)
    events.run()

    assert calls == [("a", "wake"), ("b", "wake"), ("c", "sleep"), ("d", "no arguments")]


def test_events_wait_returns_the_awaited_event(monkeypatch):
    def listen(names, on_event, timeout):
        assert names == ["wake"]
        for name in ("wake",):
            if on_event(macos.events.Event(name)):
                return

    monkeypatch.setattr(events, "_listen", listen)
    assert events.wait("wake") == macos.events.Event("wake")
    monkeypatch.setattr(events, "_listen", lambda names, on_event, timeout: None)
    assert events.wait("wake", timeout=0.1) is None


def test_events_names_cover_every_source():
    assert set(events.NAMES) >= {
        "space_changed", "app_hidden", "app_unhidden", "power_connected", "power_disconnected",
        "network_changed", "usb_connected", "usb_disconnected", "displays_changed",
    }  # fmt: skip
    assert events.Event("usb_connected", device="USB Keyboard").device == "USB Keyboard"


class _FakeObjC:
    """Stands in for the Objective-C bridge while listening: records what's sent, and makes the observer."""

    id = SEL = object()

    def __init__(self):
        self.sent = []

    def define_class(self, name, methods):
        return "class"

    def send(self, receiver, selector, *args, **kwargs):
        self.sent.append((receiver, selector))
        return {"alloc": "allocated", "init": 77}.get(selector)

    def sel(self, name):
        return name

    def nsstring(self, text):
        return text

    def autorelease_pool(self):
        import contextlib

        return contextlib.nullcontext()


def test_listen_undoes_everything_when_a_watcher_fails(monkeypatch):
    fake = _FakeObjC()
    closed = []

    class Power:
        def __init__(self, listener):
            assert listener in events._listeners.active()

        def close(self):
            closed.append("power")

    def network(listener):
        raise macos.MacOSError("configd is out of reach")

    monkeypatch.setattr(events, "_objc", fake)
    monkeypatch.setattr(events, "framework", lambda name: None)
    monkeypatch.setattr(events, "_notification_names", lambda: {"NSWorkspaceDidWakeNotification": "wake"})
    monkeypatch.setattr(events, "_center", lambda kind: kind)
    monkeypatch.setitem(events._WATCHERS, events._POWER, Power)
    monkeypatch.setitem(events._WATCHERS, events._NETWORK, network)

    with pytest.raises(macos.MacOSError, match="configd"):
        events._listen(["wake", "power_connected", "network_changed"], lambda event: True, None)

    assert closed == ["power"]  # the watcher made before is closed: its callback isn't left scheduled
    removed = [receiver for receiver, selector in fake.sent if selector == "removeObserver:"]
    assert sorted(removed) == [events._DISTRIBUTED, events._WORKSPACE]
    assert (77, "release") in fake.sent
    assert events._observers == {} and events._listeners.active() == []


def test_errors_in_the_notification_callback_come_out_of_the_listener(monkeypatch):
    from macos import _events

    listener = _events.Listener()
    monkeypatch.setitem(events._observers, 5, listener)

    def broken(notification):
        raise LookupError("unreadable notification")

    monkeypatch.setattr(events, "_event", broken)
    events._handle(5, 0, 0)  # what AppKit calls: it must not raise
    events._handle(6, 0, 0)  # an observer being removed: ignored
    monkeypatch.setattr(events._events._objc, "spin", lambda seconds: None)
    with pytest.raises(LookupError, match="unreadable"):
        list(listener.drain(1))


def test_watchers_close_what_they_made_when_they_fail(monkeypatch):
    from macos import _events

    released = []
    monkeypatch.setattr(events._cf, "release", lambda ref: released.append(ref))

    class Store:
        def SCDynamicStoreCreate(self, *args):
            return 0  # configd unreachable

    monkeypatch.setattr(events._sc, "lib", Store)
    monkeypatch.setattr(events._cf, "string", lambda text: 1)
    with pytest.raises(macos.MacOSError, match="could not watch the network"):
        events._NetworkWatch(_events.Listener())

    class Ports:
        destroyed = []

        def IONotificationPortCreate(self, port):
            return 9

        def IOServiceMatching(self, name):
            return 3

        def IOServiceAddMatchingNotification(self, *args):
            return -536870201  # kIOReturnNoMemory, as a signed int

        def IONotificationPortDestroy(self, port):
            self.destroyed.append(port)

    monkeypatch.setattr(events._iokit, "lib", Ports)
    with pytest.raises(macos.MacOSError, match="IOReturn 0xe00002c7"):
        events._USBWatch(_events.Listener())
    assert Ports.destroyed == [9]

    class Displays:
        def CGDisplayRegisterReconfigurationCallback(self, callback, info):
            return 0

        def CGDisplayRemoveReconfigurationCallback(self, callback, info):
            released.append("display callback")

    monkeypatch.setattr(_events, "graphics", Displays)
    released.clear()
    listener = _events.Listener()
    displays = events._DisplayWatch(listener)
    for display, flags in ((1, 1), (1, 16), (2, 16)):  # "about to change", then two displays
        displays.changed(display, flags, None)
    displays.close()
    displays.close()  # twice is harmless
    assert list(listener.pending) == [events.Event("displays_changed")]
    assert released == ["display callback"]


def test_stop_reaches_every_run_and_wait():
    from macos import _events

    first, second = _events.Listener(), _events.Listener()
    with events._listeners.listening(first), events._listeners.listening(second):
        events.stop()
    assert first.stop.is_set() and second.stop.is_set()
    later = _events.Listener()
    with events._listeners.listening(later):
        assert not later.stop.is_set()  # a stop() is for the calls in progress only


def test_at_the_timeout_queued_events_come_but_no_later_ones(monkeypatch):
    from macos import _events

    clock = [0.0]
    monkeypatch.setattr(_events.time, "monotonic", lambda: clock[0])
    listener = _events.Listener()
    listener.pending.extend(range(4))  # queued by the tap's thread while callbacks ran

    handled = []
    for item in listener.drain(timeout=1.0):
        handled.append(item)
        clock[0] += 0.4  # each callback takes 0.4 s...
        listener.pending.append(100 + item)  # ...while one more event comes in
    # Everything queued by the time it ran out comes, none of what kept coming after: no event is lost,
    # and a steady stream can't keep it going past the timeout.
    assert handled == [0, 1, 2, 3, 100, 101, 102]
